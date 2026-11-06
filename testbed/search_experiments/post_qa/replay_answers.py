"""Optional paid replay of captured final Responses requests. No query/graph calls."""
import argparse
import copy
import json
import time
from pathlib import Path
from budget_lab import ROOT, read, write, digest, context, round_robin, paid_client


def build_request(case, selected, options):
    """Keep actual first-turn messages, images, tool calls and app instructions intact."""
    if 'final_request' not in case:
        raise ValueError('Missing captured final_request; cannot claim exact app replay')
    request = copy.deepcopy(case['final_request'])
    if request.get('tool_choice') != 'none' or not request.get('instructions'):
        raise ValueError('capture the final answer request, with tool_choice=none')
    if 'previous_response_id' in request or 'conversation' in request:
        raise ValueError('self-contained input required; no hidden server conversation')
    calls = [x for x in request['input'] if x.get('type') == 'function_call']
    outputs = [x for x in request['input'] if x.get('type') == 'function_call_output']
    if len(calls) != len(case['results']) or len(outputs) != len(calls):
        raise ValueError('tool/results count mismatch')
    order = {c['call_id']: i for i,c in enumerate(calls)}
    if {x['call_id'] for x in outputs} != set(order):
        raise ValueError('tool call IDs mismatch')
    for c,r in zip(calls,case['results']):
        if json.loads(c['arguments'])['query'] != r['query']:
            raise ValueError('captured query order mismatch')
    # Same first-occurrence ownership as original round robin, including shared hits.
    owners = {}
    for pair in round_robin([[(i,m) for m in r['memories']] for i,r in enumerate(case['results'])]):
        i,m = pair
        owners.setdefault(m['id'],i)
    for output in outputs:
        chosen = [m for m in selected if owners[m['id']] == order[output['call_id']]]
        output['output'] = json.dumps(context(chosen),ensure_ascii=False)
    request.update(options)
    request['store'] = False
    return request


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bundle',required=True)
    p.add_argument('--comparison',required=True)
    p.add_argument('--schedule',required=True)
    p.add_argument('--config',default=str(ROOT/'config.json'))
    p.add_argument('--output',default=str(ROOT/'outputs/answers.jsonl'))
    p.add_argument('--allow-paid',action='store_true')
    a=p.parse_args()
    bundle,comparison,config=read(a.bundle),read(a.comparison),read(a.config)
    if comparison['bundle_hash']!=digest(bundle) or comparison['config_hash']!=digest(config):
        raise ValueError('comparison inputs changed')
    cases={c['id']:c for c in bundle['cases']}
    rows={(r['case_id'],r['mode']):r for r in comparison['rows']}
    jobs=read(a.schedule)
    requests=[]
    for cid,repeat,mode in jobs:
        row=rows[cid,mode]
        if row['status']!='selected':
            raise ValueError('all rank caches required before answer replay')
        requests.append((cid,repeat,mode,build_request(cases[cid],row['selected'],config['answer_options'])))
    if not a.allow_paid:
        print(json.dumps({'prepared_answer_calls':len(requests),'network_calls':0,'status':'dry-run'}))
        return
    output=Path(a.output);output.parent.mkdir(parents=True,exist_ok=True)
    done={}
    if output.exists():
        done={r['job_key']:r for r in map(json.loads,output.read_text().splitlines())}
    client=paid_client(a.allow_paid)
    for cid,repeat,mode,request in requests:
        key=digest({'bundle':comparison['bundle_hash'],'config':config,'case':cid,'repeat':repeat,'mode':mode,'request':request})
        if key in done:continue
        start=time.perf_counter()
        try:
            response=client.responses.create(**request)
            result={'status':response.status,'text':response.output_text,
                    'usage':response.usage.model_dump() if response.usage else None,
                    'response_id':response.id,'model':response.model,'service_tier':getattr(response,'service_tier',None)}
        except Exception as error:
            # Do not write keys, request bodies or server exception text.
            result={'status':'error','error_type':type(error).__name__,'usage':None}
        result.update(job_key=key,case_id=cid,repeat=repeat,mode=mode,answer_seconds=time.perf_counter()-start)
        with output.open('a') as f:f.write(json.dumps(result,ensure_ascii=False)+'\n')
        if result['status']!='completed':
            raise RuntimeError('Stopped on failed/incomplete call. Inspect saved attempt before resuming.')


if __name__=='__main__':main()
