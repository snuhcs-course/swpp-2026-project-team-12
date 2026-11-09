"""Pinned 855cd61 selector: fact 5 + episode 5, archived QA prompt and retrieval.
Reuses transport and grading protocol; no shared app edits.
"""
import argparse
import os
from pathlib import Path
import json
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
OUT=Path(os.environ.get('SEARCH_EXPERIMENT_OUTPUT', ROOT/'outputs/separate_budget_855cd61_100'))
LOCK=threading.Lock()

def append(path,value):
    with LOCK:
        base.pilot.append(path,value)

def prepare():
    """Execute the pinned app selector unchanged and retain the archived QA request."""
    import ast
    import copy
    from budget_lab import context, selection_metrics
    OUT.mkdir(parents=True,exist_ok=True)
    config=read(SOURCE/'config.json')
    branch_prompts=module('branch_prompts_855cd61',ROOT/'candidate_selectors/prompts_855cd61.py')
    assert branch_prompts.FACT_BUDGET==5
    source=ROOT/'candidate_selectors/post_flow_855cd61.py'
    tree=ast.parse(source.read_text())
    functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('select_budget','context')]
    namespace={'prompts':branch_prompts}
    exec(compile(ast.Module(body=functions,type_ignores=[]),str(source),'exec'),namespace)
    selector=namespace['select_budget']
    def kind(m):return 'episode' if m.get('source_episode_ids')==[m['id']] else 'fact'
    # Boundary checks: independent caps, duplicate IDs, query distribution, empty input.
    facts=[{'id':f'f{i}','source_episode_ids':[f's{i}']} for i in range(8)]
    episodes=[{'id':f'e{i}','source_episode_ids':[f'e{i}']} for i in range(8)]
    probe=selector([{'query':'q1','memories':facts+episodes},{'query':'q2','memories':facts+episodes}])
    flat=[m for r in probe for m in r['memories']]
    assert [sum(kind(m)==k for m in flat) for k in ('fact','episode')]==[5,5]
    assert len({m['id'] for m in flat})==10 and selector([])==[]
    flat=[m for r in selector([{'query':'q','memories':facts[:2]+episodes}]) for m in r['memories']]
    assert [sum(kind(m)==k for m in flat) for k in ('fact','episode')]==[2,5]
    cases={c['id']:c for c in read(SOURCE/'bundle.json')['cases']}
    selected={(r['case_id'],r['mode']):r for r in read(SOURCE/'selection_comparison.json')['rows']}
    answers={(r['case_id'],r['mode']):r for r in rows(SOURCE/'answers.jsonl')}
    grades={(r['case_id'],r['mode']):r for r in rows(SOURCE/'grades.jsonl')}
    assert len(cases)==100
    assert digest([r['case'] for r in base.ALL])==digest([r['case'] for r in read(SOURCE/'original_cases.json')])
    jobs=[];selection_rows=[]
    for cid,repeat,mode in read(SOURCE/'schedule.json'):
        if mode!='interleave':continue
        for arm in ('baseline','interleave'):
            original=build_request(cases[cid],selected[cid,arm]['selected'],config['answer_options'])
            assert answers[cid,arm]['status']=='completed' and digest(original)==answers[cid,arm]['request_hash'],(cid,arm)
            assert (cid,arm) in grades
        assert original['instructions']==branch_prompts.POST_QA+'\n'+branch_prompts.POST_QA_RETRIEVAL
        raw=copy.deepcopy(cases[cid]['results']);rawhash=digest(raw)
        chosen=selector(raw)
        assert digest(raw)==rawhash
        memories=[m for r in chosen for m in r['memories']]
        counts={k:sum(kind(m)==k for m in memories) for k in ('fact','episode')}
        assert counts['fact']<=5 and counts['episode']<=5
        request=build_request(cases[cid],memories,config['answer_options'])
        def stripped(req):
            req=copy.deepcopy(req)
            for item in req['input']:
                if item.get('type')=='function_call_output':item['output']='<MEMORIES>'
            return req
        assert stripped(request)==stripped(original),'Only selected tool memories may change'
        outputs=[i for i in request['input'] if i.get('type')=='function_call_output']
        for output,result in zip(outputs,chosen):
            assert json.loads(output['output'])==namespace['context'](result['memories'])
        selection_rows.append({'case_id':cid,'mode':'separate_5_5','selected':memories,'by_query':chosen,
                               'metrics':selection_metrics(cases[cid],memories),'counts':counts})
        jobs.append((cid,request))
    assert len(jobs)==100
    locked_files=['answers.jsonl','grades.jsonl','selection_comparison.json','original_cases.json','config.json','retrieval.json','bundle.json']
    lock={'source':str(SOURCE),'cases':100,'repeats':1,'selection':'separate_5_5',
          'branch_commit':'855cd61fd33e2a6ab2bf28a2b783e7b2c690bfcd','changed_request_fields':['input.function_call_output.output'],
          'answer_options':config['answer_options'],'gold_hash':digest([r['case'] for r in base.ALL]),
          'prompt_sha256':hashlib.sha256(original['instructions'].encode()).hexdigest(),
          'selector_source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
          'judge_sha256':hashlib.sha256((ROOT/'frozen/judge_reference.py').read_bytes()).hexdigest(),
          'source_hashes':{f:hashlib.sha256((SOURCE/f).read_bytes()).hexdigest() for f in locked_files},
          'request_hashes':{cid:digest(req) for cid,req in jobs},'selection_hash':digest(selection_rows)}
    path=OUT/'manifest.json'
    if path.exists():
        previous=read(path)
        previous['source']=str(SOURCE)  # Only the archive location may move.
        assert previous==lock,'Frozen inputs changed'
    else:
        write(path,lock)
        shutil.copytree(SOURCE/'judge_cache',OUT/'judge_cache',dirs_exist_ok=True)
        (OUT/'qa_prompt.txt').write_text(original['instructions'])
        write(OUT/'selection_comparison.json',{'rows':selection_rows})
    assert digest(read(OUT/'selection_comparison.json')['rows'])==lock['selection_hash']
    print('Verified 200 archived A/B requests; pinned app selector; same QA/gold/judge; 100 new requests ready',flush=True)
    from statistics import mean
    print('Offline required-label recall:',mean(r['metrics']['required_recall'] for r in selection_rows),
          'mean facts/episodes:',mean(r['counts']['fact'] for r in selection_rows),mean(r['counts']['episode'] for r in selection_rows),flush=True)
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
                record={'case_id':cid,'repeat':1,'mode':'separate_5_5','request_hash':digest(request),
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
    judge=module('separate_budget_judge',ROOT/'frozen/judge_reference.py')
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
            rec={'case_id':cid,'repeat':1,'mode':'separate_5_5',**result}
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
