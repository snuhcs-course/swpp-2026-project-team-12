"""Fixed interleave memories: archived QA prompt A vs answer-only prompt B.
No shared app, retrieval, gold, or judge changes. Resume completed paid calls.
"""
import argparse
import os
from pathlib import Path
import concurrent.futures
import hashlib
import shutil
import threading
import time
from types import SimpleNamespace
from budget_lab import read, write, digest, paid_client
from replay_answers import build_request
import run_full_once as base
from run_pilot import rows, load_key, module, DATA

ROOT=base.ROOT
SOURCE=base.OUT
OUT=Path(os.environ.get('SEARCH_EXPERIMENT_OUTPUT', ROOT/'outputs/qa_interleave_v2_100'))
PROMPT=ROOT/'candidate_prompts/post_qa_v2.txt'
LOCK=threading.Lock()

def append(path,value):
    with LOCK:
        base.pilot.append(path,value)

def prepare():
    OUT.mkdir(parents=True,exist_ok=True)
    config=read(SOURCE/'config.json')
    cases={c['id']:c for c in read(SOURCE/'bundle.json')['cases']}
    selected={r['case_id']:r for r in read(SOURCE/'selection_comparison.json')['rows'] if r['mode']=='interleave'}
    answers={r['case_id']:r for r in rows(SOURCE/'answers.jsonl') if r['mode']=='interleave'}
    grades={r['case_id']:r for r in rows(SOURCE/'grades.jsonl') if r['mode']=='interleave'}
    assert len(cases)==len(selected)==len(answers)==len(grades)==100
    assert digest([r['case'] for r in base.ALL])==digest([r['case'] for r in read(SOURCE/'original_cases.json')])
    prompt=PROMPT.read_text()
    jobs=[]
    old_prompt=None
    for cid,repeat,mode in read(SOURCE/'schedule.json'):
        if mode!='interleave':continue
        req=build_request(cases[cid],selected[cid]['selected'],config['answer_options'])
        assert answers[cid]['status']=='completed' and digest(req)==answers[cid]['request_hash'], cid
        if old_prompt is None:old_prompt=req['instructions']
        assert req['instructions']==old_prompt
        original_hash=digest({k:v for k,v in req.items() if k!='instructions'})
        req['instructions']=prompt
        assert digest({k:v for k,v in req.items() if k!='instructions'})==original_hash
        jobs.append((cid,req))
    locked_files=['answers.jsonl','grades.jsonl','selection_comparison.json','original_cases.json','config.json','retrieval.json']
    lock={'source':str(SOURCE),'cases':100,'repeats':1,'selection':'interleave','changed_request_fields':['instructions'],
          'answer_options':config['answer_options'],'gold_hash':digest([r['case'] for r in base.ALL]),
          'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),
          'judge_sha256':hashlib.sha256((ROOT/'frozen/judge_reference.py').read_bytes()).hexdigest(),
          'source_hashes':{f:hashlib.sha256((SOURCE/f).read_bytes()).hexdigest() for f in locked_files},
          'request_hashes':{cid:digest(req) for cid,req in jobs}}
    path=OUT/'manifest.json'
    if path.exists():
        previous=read(path)
        previous['source']=str(SOURCE)  # Only the archive location may move.
        assert previous==lock,'Frozen inputs changed'
    else:
        write(path,lock)
        shutil.copytree(SOURCE/'judge_cache',OUT/'judge_cache',dirs_exist_ok=True)
        (OUT/'prompt_A.txt').write_text(old_prompt)
        (OUT/'prompt_B.txt').write_text(prompt)
    assert (OUT/'prompt_B.txt').read_text()==prompt
    print('Verified 100 archived request hashes; B changes instructions only; gold/selection/judge unchanged',flush=True)
    return jobs

def answer(jobs):
    done={r['case_id'] for r in rows(OUT/'answers.jsonl')}
    terminal={r['case_id'] for r in rows(OUT/'terminal_errors.jsonl')}
    with paid_client(True) as client:
        for cid,request in jobs:
            if cid in done or cid in terminal:continue
            for attempt in range(1,4):
                start=time.perf_counter()
                try:
                    response=client.responses.create(**request)
                except Exception as error:
                    rec={'case_id':cid,'attempt':attempt,'request_hash':digest(request),
                         'causes':base.causes(error),'seconds':time.perf_counter()-start,'usage':None}
                    append(OUT/'answer_errors.jsonl',rec)
                    if any(e['status']==400 and e['code']=='invalid_prompt' for e in rec['causes']):
                        append(OUT/'terminal_errors.jsonl',rec)
                        terminal.add(cid)
                        break
                    if base.transient(error) and attempt<3:
                        time.sleep(2)
                        continue
                    raise RuntimeError('Answer stopped; safe error log saved, completed calls preserved') from None
                record={'case_id':cid,'repeat':1,'mode':'qa_v2','request_hash':digest(request),
                    'status':response.status,'text':response.output_text,'response_id':response.id,
                    'model':response.model,'service_tier':response.service_tier,
                    'usage':response.usage.model_dump(),'answer_seconds':time.perf_counter()-start}
                append(OUT/'answers.jsonl',record)
                done.add(cid)
                if response.status!='completed':
                    append(OUT/'terminal_errors.jsonl',{'case_id':cid,'status':response.status,'note':'Billed incomplete response retained; no content-based retry'})
                print('answered',len(done),cid,round(record['answer_seconds'],2),flush=True)
                break

def grade():
    from openai import OpenAI
    judge=module('qa_v2_judge',ROOT/'frozen/judge_reference.py')
    cases={r['case']['id']:r for r in base.ALL}
    answers=rows(OUT/'answers.jsonl')
    terminal={r['case_id'] for r in rows(OUT/'terminal_errors.jsonl')}
    assert len({a['case_id'] for a in answers}|terminal)==100
    done={g['case_id'] for g in rows(OUT/'grades.jsonl')}
    pending=[a for a in answers if a['status']=='completed' and a['case_id'] not in done]
    stop=threading.Event()
    client=OpenAI(timeout=120,max_retries=0)
    def one(a):
        if stop.is_set():return
        cid=a['case_id']
        class Meter:
            def create(self,**kwargs):
                for attempt in range(1,4):
                    started=time.perf_counter()
                    try:response=client.responses.create(**kwargs)
                    except Exception as error:
                        append(OUT/'judge_errors.jsonl',{'case_id':cid,'attempt':attempt,'causes':base.causes(error),'seconds':time.perf_counter()-started,'usage':None})
                        if not base.transient(error) or attempt==3:raise
                        time.sleep(2)
                        continue
                    append(OUT/'judge_calls.jsonl',{'case_id':cid,'seconds':time.perf_counter()-started,'model':response.model,
                        'service_tier':response.service_tier,'status':response.status,'usage':response.usage.model_dump(),'response_id':response.id})
                    return response
        try:
            evaluator=judge.Judge(OUT/'judge_cache',model='gpt-6-luna',client=SimpleNamespace(responses=Meter()))
            assert evaluator.reasoning_effort is None
            c=cases[cid]['case'];output={'text':a['text'],'queries':cases[cid]['output']['queries']}
            result=evaluator.evaluate('post_qa',c,output,judge.judge_material('post_qa',c,output),judge.judge_images('post_qa',c,DATA))
            rec={'case_id':cid,'repeat':1,'mode':'qa_v2',**result}
            append(OUT/'grades.jsonl',rec)
            print('graded',cid,result['verdicts']['correct']['pass'],flush=True)
            return rec
        except Exception as error:
            stop.set()
            append(OUT/'stage_errors.jsonl',{'stage':'grade','case_id':cid,'causes':base.causes(error)})
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(one,pending))
    finally:client.close()
    assert len(rows(OUT/'grades.jsonl'))==sum(a['status']=='completed' for a in answers),'Grading incomplete; resume saved work'

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['prepare','answer','grade','run']);p.add_argument('--allow-paid',action='store_true');args=p.parse_args()
    jobs=prepare()
    if args.stage!='prepare':
        if not args.allow_paid:raise RuntimeError('--allow-paid required')
        load_key()
        if args.stage in ('answer','run'):answer(jobs)
        if args.stage in ('grade','run'):grade()
