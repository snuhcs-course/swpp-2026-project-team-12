"""Expand the frozen pilot to 100 cases x 3 selectors x one repeat.

Reuse completed pilot cases only after exact request/selection/gold checks.
Answers remain sequential. Grading is independent and uses four workers after
all answers finish; rubric and model options are unchanged.
"""
import argparse
import asyncio
import concurrent.futures
import hashlib
import json
import shutil
import threading
import time
from types import SimpleNamespace

import run_pilot as pilot
from budget_lab import read, write, digest, compare, rank_key, validate_bundle
from replay_answers import build_request

ROOT=pilot.ROOT
PILOT=ROOT/'outputs/pilot60'
OUT=ROOT/'outputs/full300_once'
CONFIG=read(ROOT/'pilot_config.json')
assert CONFIG['repeats']==1
ALL=read(pilot.DATA/'feature_eval/post_qa.json')['cases']
assert len(ALL)==100 and len({r['case']['id'] for r in ALL})==100
pilot.OUT=OUT
pilot.originals=lambda: ALL
LOCK=threading.Lock()


def append(path, value):
    with LOCK:
        pilot.append(path,value)


def initialize():
    marker=OUT/'pilot_reuse.json'
    if marker.exists():
        return
    assert not OUT.exists(), 'Do not merge into an unverified existing output directory'
    OUT.mkdir(parents=True)
    names=['retrieval.json','embedding_calls.jsonl','ranks.json','ranks.json.attempts.jsonl',
           'answers.jsonl','grades.jsonl','judge_calls.jsonl','answer_errors.jsonl','judge_errors.jsonl']
    hashes={}
    for name in names:
        path=PILOT/name
        if path.exists():
            shutil.copyfile(path,OUT/name)
            hashes[name]=hashlib.sha256(path.read_bytes()).hexdigest()
    shutil.copytree(PILOT/'judge_cache',OUT/'judge_cache')
    write(OUT/'config.json',CONFIG)
    write(marker,{'pilot_directory':str(PILOT),'copied_file_hashes':hashes,
                  'reused_answers':60,'reused_grades':60,'additional_answers_planned':240,
                  'case_count':100,'repeats':1,'modes':['baseline','interleave','reranker']})
    print('Initialized full 300; preserved pilot 60',flush=True)


def preflight():
    new=read(OUT/'bundle.json');old=read(PILOT/'bundle.json')
    validate_bundle(new)
    byid={c['id']:c for c in new['cases']}
    for c in old['cases']:
        assert c==byid[c['id']], f"Pilot case changed: {c['id']}"
    assert len(read(OUT/'schedule.json'))==300
    assert {r for cid,r,m in read(OUT/'schedule.json')}=={1}
    assert CONFIG==read(ROOT/'pilot_config.json')
    assert [r for r in ALL if r['case']['viewer_username']=='week_jimin']==read(PILOT/'original_cases.json')
    ranks=read(OUT/'ranks.json')
    result=compare(new,ranks,CONFIG)
    selections={(r['case_id'],r['mode']):r for r in result['rows']}
    oldsel={(r['case_id'],r['mode']):r for r in read(PILOT/'selection_comparison.json')['rows']}
    for a in pilot.rows(PILOT/'answers.jsonl'):
        row=selections[a['case_id'],a['mode']]
        assert row['selected']==oldsel[a['case_id'],a['mode']]['selected']
        request=build_request(byid[a['case_id']],row['selected'],CONFIG['answer_options'])
        assert digest(request)==a['request_hash'], 'Do not reuse a mismatched answer'
    write(OUT/'preflight.json',{'cases':100,'jobs':300,'repeats':1,'pilot_cases_identical':20,
          'pilot_request_hashes_identical':60,'gold_unchanged':True,'paid_calls_during_preflight':0})
    print('Preflight passed: 60 pilot request hashes identical, 240 answers pending',flush=True)


def safe_error(error):
    body=getattr(error,'body',None)
    code=body.get('code') if isinstance(body,dict) else None
    if isinstance(body,dict) and isinstance(body.get('error'),dict):code=body['error'].get('code',code)
    return {'type':type(error).__name__,'status':getattr(error,'status_code',None),'code':code}


def causes(error):
    found=[];seen=set();todo=[error]
    while todo:
        x=todo.pop()
        if id(x) in seen:continue
        seen.add(id(x));found.append(safe_error(x))
        todo.extend(getattr(x,'exceptions',[]))
        if x.__cause__:todo.append(x.__cause__)
        if x.__context__:todo.append(x.__context__)
    return found


def transient(error):
    for e in causes(error):
        if e['code'] in ('credit_balance_exhausted','insufficient_quota','billing_hard_limit_reached'):
            return False
    return any(e['type'] in ('APITimeoutError','APIConnectionError','InternalServerError')
               or e['status'] in (408,409,500,502,503,504)
               or (e['status']==429 and e['code']=='rate_limit_exceeded') for e in causes(error))


def execute_stage(stage):
    pilot.TERMINAL_ANSWER_KEYS={(r['case_id'],r['repeat'],r['mode']) for r in pilot.rows(OUT/'terminal_errors.jsonl')}
    for attempt in range(1,4):
        try:
            if stage=='retrieve':asyncio.run(pilot.retrieve())
            else:getattr(pilot,stage)()
            return
        except Exception as error:
            info={'stage':stage,'attempt':attempt,'causes':causes(error)}
            append(OUT/'stage_errors.jsonl',info)
            if stage=='answer' and any(e['status']==400 and e['code']=='invalid_prompt' for e in causes(error)):
                # Never retry or alter a rejected prompt. Keep this case ungraded.
                record=pilot.rows(OUT/'answer_errors.jsonl')[-1]
                key=(record['case_id'],record['repeat'],record['mode'])
                if key not in pilot.TERMINAL_ANSWER_KEYS:
                    append(OUT/'terminal_errors.jsonl',{**record,'status':'api_rejected','code':'invalid_prompt',
                        'note':'Input kept unchanged; rejected request not retried; no answer or judge verdict.'})
                pilot.TERMINAL_ANSWER_KEYS.add(key)
                print('Recorded ungraded API rejection; continue other cases',key,flush=True)
                continue
            if attempt==3 or not transient(error):
                raise RuntimeError('Stage stopped; safe details in stage_errors.jsonl; completed work preserved') from None
            print('Transient failure; resume cached stage',stage,attempt,flush=True)
            time.sleep(2)


def grade():
    from openai import OpenAI
    judge=pilot.module('full_judge',ROOT/'frozen/judge_reference.py')
    cases={r['case']['id']:r for r in ALL}
    completed={(r['case_id'],r['repeat'],r['mode']) for r in pilot.rows(OUT/'grades.jsonl')}
    answers=pilot.rows(OUT/'answers.jsonl')
    terminal=pilot.rows(OUT/'terminal_errors.jsonl')
    terminal_keys={(a['case_id'],a['repeat'],a['mode']) for a in terminal}
    assert len(answers)+len(terminal_keys)==300 and all(a['status']=='completed' for a in answers)
    pending=[a for a in answers if (a['case_id'],a['repeat'],a['mode']) not in completed]
    stop=threading.Event()
    client=OpenAI(timeout=120,max_retries=0)

    def one(a):
        if stop.is_set():return None
        key=(a['case_id'],a['repeat'],a['mode'])
        class Meter:
            def create(self,**kwargs):
                for attempt in range(1,4):
                    started=time.perf_counter()
                    try:
                        response=client.responses.create(**kwargs)
                    except Exception as error:
                        append(OUT/'judge_errors.jsonl',{'job':key,'attempt':attempt,
                            'causes':causes(error),'seconds':time.perf_counter()-started,'usage':None})
                        if not transient(error) or attempt==3:raise
                        time.sleep(2)
                        continue
                    append(OUT/'judge_calls.jsonl',{'job':key,'seconds':time.perf_counter()-started,
                        'model':response.model,'service_tier':response.service_tier,
                        'status':response.status,'usage':response.usage.model_dump(),'response_id':response.id})
                    return response
        evaluator=judge.Judge(OUT/'judge_cache',model='gpt-6-luna',client=SimpleNamespace(responses=Meter()))
        assert evaluator.reasoning_effort is None
        c=cases[a['case_id']]['case']
        output={'text':a['text'],'queries':cases[a['case_id']]['output']['queries']}
        try:
            result=evaluator.evaluate('post_qa',c,output,judge.judge_material('post_qa',c,output),judge.judge_images('post_qa',c,pilot.DATA))
            return {'case_id':key[0],'repeat':1,'mode':key[2],**result}
        except Exception as error:
            stop.set()
            append(OUT/'stage_errors.jsonl',{'stage':'grade','job':key,'causes':causes(error)})
            return None

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            for result in pool.map(one,pending):
                if result is None:continue
                append(OUT/'grades.jsonl',result)
                completed.add((result['case_id'],result['repeat'],result['mode']))
                print('graded',len(completed),result['case_id'],result['mode'],result['verdicts']['correct']['pass'],flush=True)
    finally:client.close()
    if len(completed)+len(terminal_keys)!=300:raise RuntimeError('Grading incomplete; cached completed work preserved')


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('stage',choices=['init','retrieve','prepare','rank','preflight','answer','grade'])
    p.add_argument('--allow-paid',action='store_true')
    a=p.parse_args()
    if a.stage in ('retrieve','rank','answer','grade'):
        if not a.allow_paid:raise RuntimeError('Explicit --allow-paid required')
        pilot.load_key()
    if a.stage=='init':initialize()
    elif a.stage=='prepare':pilot.build_bundle();preflight()
    elif a.stage=='preflight':preflight()
    elif a.stage=='grade':grade()
    else:execute_stage(a.stage)
