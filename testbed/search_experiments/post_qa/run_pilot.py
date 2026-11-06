"""Controlled 20-question, three-selector pilot; never imports shared app code.

Frozen original queries replace the query-decision turn. New requests are explicitly
reconstructed, not historical request captures. Gold and grading stay unchanged.
"""
import argparse
import asyncio
import base64
import importlib.util
import json
import os
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from budget_lab import ROOT, read, write, digest, validate_bundle, prepare, compare, paid_rank, paid_client
from replay_answers import build_request

DATA = ROOT/'inputs/team_export/testbed_output/family-week-100-five-members'
OUT = ROOT/'outputs/pilot60'
CONFIG = read(ROOT/'pilot_config.json')
TERMINAL_ANSWER_KEYS = set()


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def append(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as f:
        f.write(json.dumps(value, ensure_ascii=False)+'\n')


def originals():
    return [r for r in read(DATA/'feature_eval/post_qa.json')['cases']
            if r['case']['viewer_username'] == 'week_jimin']


def load_key():
    key = os.environ.get('OPENAI_API_KEY')
    if not key:
        raise RuntimeError('API key missing')
    os.environ['OPENAI_API_KEY'] = key
    os.environ['GRAPHITI_TELEMETRY_ENABLED'] = 'false'


async def retrieve():
    from openai import AsyncOpenAI
    from graphiti_core import Graphiti
    from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
    from runtime_search.searching_graphiti import search_many
    from neo4j import GraphDatabase
    private = {'uri':os.environ['NEO4J_URI'], 'user':os.environ.get('NEO4J_USER','neo4j'), 'password':os.environ['NEO4J_PASSWORD']}
    with GraphDatabase.driver(private['uri'], auth=(private['user'], private['password'])) as driver:
        with driver.session() as session:
            session.run('CALL db.awaitIndexes(60)').consume()
            nodes = session.run('MATCH (n) RETURN count(n) AS n').single()['n']
            edges = session.run('MATCH ()-[r]->() RETURN count(r) AS n').single()['n']
            episodes = session.run("MATCH (e:Episodic) WHERE e.name STARTS WITH 'post_' RETURN count(e) AS n, collect(DISTINCT size(e.content_embedding)) AS dims").single().data()
        assert nodes == 105 and edges == 281 and episodes == {'n': 80, 'dims': [1024]}
        write(OUT/'graph_verification.json', dict(nodes=nodes, edges=edges, episodes=episodes))

    class MeteredEmbedder(OpenAIEmbedder):
        async def create(self, input_data):
            started = time.perf_counter()
            response = await self.client.embeddings.create(input=input_data, model=self.config.embedding_model)
            append(OUT/'embedding_calls.jsonl', {'case_id':self.case_id, 'query':input_data,
                'seconds':time.perf_counter()-started, 'model':response.model,
                'usage':response.usage.model_dump()})
            # Match Graphiti 0.31.1: request full embedding then truncate, not dimensions=1024.
            return response.data[0].embedding[:self.config.embedding_dim]

    client = AsyncOpenAI(timeout=60, max_retries=0)
    embedder = MeteredEmbedder(OpenAIEmbedderConfig(), client=client)
    graph = Graphiti(private['uri'], private['user'], private['password'], embedder=embedder)
    cache = read(OUT/'retrieval.json') if (OUT/'retrieval.json').exists() else {}
    try:
        for row in originals():
            c = row['case']; cid = c['id']
            if cid in cache:
                continue
            embedder.case_id = cid
            queries = row['output']['queries']
            started = time.perf_counter()
            result = await search_many(graph, 5971, queries, max_queries=5)
            cache[cid] = {'results':result, 'seconds':time.perf_counter()-started}
            write(OUT/'retrieval.json',cache)
            print('retrieved', cid, sum(len(r['memories']) for r in result), flush=True)
    finally:
        await graph.close()
        await client.close()


def build_bundle():
    prompts = module('pilot_prompts', ROOT/'frozen/app_prompts.py')
    report = read(DATA/'feature_eval/post_qa.json')
    # The exact historical per-call timestamp was not exported. Freeze the report timestamp.
    at = report['evaluated_at']
    manifest, state = read(DATA/'manifest.json'), read(DATA/'database_state.json')
    events = {e['feed_key']:e for e in manifest['events']}
    names = {f'post_{pid}':key for key,pid in state['post_ids'].items()}
    retrieved = read(OUT/'retrieval.json')
    cases = []
    for row in originals():
        c = row['case']; results = retrieved[c['id']]['results']
        # Neo4j toString may append [UTC]; preserve the instant in Python ISO form.
        for r in results:
            for m in r['memories']:
                for source in m['sources']:
                    value=source['recorded_at']
                    source['recorded_at']=datetime.fromisoformat(value.split('[')[0]).isoformat()
        text = json.dumps({'작성자':c['author_name'], '관계':c['expected_relationship'],
            '원문':c['caption'],'게시시각':c['created_at'],'질문':c['question'],
            '질문자':c['viewer_name'],'이전대화':c['prior_dialogue'],'현재시각':at},ensure_ascii=False)
        content = [{'type':'input_text','text':text}]
        for image in c['image_paths']:
            content.append({'type':'input_image','detail':'high',
                'image_url':'data:image/jpeg;base64,'+base64.b64encode((DATA/image).read_bytes()).decode()})
        inputs = [{'role':'user','content':content}]
        for i,r in enumerate(results):
            inputs.append({'type':'function_call','call_id':f'pilot_call_{i}',
                'name':prompts.POST_QA_SEARCH_TOOL['name'],
                'arguments':json.dumps({'query':r['query']},ensure_ascii=False)})
        for i,r in enumerate(results):
            inputs.append({'type':'function_call_output','call_id':f'pilot_call_{i}','output':'{}'})
        labels = {}
        for r in results:
            for m in r['memories']:
                for s in m['sources']:
                    key = names.get(s['name'])
                    assert key is not None or not s['name'].startswith('post_')
                    labels[s['id']] = events[key].get('establishes',[]) if key else []
        request = {'instructions':prompts.POST_QA+'\n'+prompts.POST_QA_RETRIEVAL,
            'input':inputs,'tools':[prompts.POST_QA_SEARCH_TOOL],'tool_choice':'none','store':False}
        cases.append({'id':c['id'],'probe_id':c['feed_key'],'question':c['question'],
            'question_at':at,'input_text':text,'results':results,'source_labels':labels,
            'gold':{k:c.get(k,[]) for k in ('required_memories','optional_memories','must_filter','reference','stale_reference')},
            'final_request':request})
    bundle = {'schema_version':1,'synthetic':False,
        'request_origin':'reconstructed controlled replay, not captured historical requests',
        'query_policy':'stored original queries, no new decision turn',
        'cases':cases}
    assert len(cases)==len(originals())
    validate_bundle(bundle)
    write(OUT/'bundle.json',bundle)
    prepare(bundle,CONFIG,OUT)
    # Full untouched original case objects preserve every question, gold and grader input.
    write(OUT/'original_cases.json',originals())
    print(f'prepared {len(cases)} cases / {len(cases)*3} scheduled answers; gold hash',digest([r['case'] for r in originals()]),flush=True)


def rank():
    bundle = read(OUT/'bundle.json')
    ranks = paid_rank(bundle, CONFIG, OUT/'ranks.json', True)
    result = compare(bundle, ranks, CONFIG)
    write(OUT/'selection_comparison.json',result)
    print('ranked',len(ranks),'cases',flush=True)


def answer():
    bundle = read(OUT/'bundle.json'); comparison = read(OUT/'selection_comparison.json')
    assert comparison['bundle_hash']==digest(bundle) and comparison['config_hash']==digest(CONFIG)
    cases={c['id']:c for c in bundle['cases']}
    selections={(r['case_id'],r['mode']):r for r in comparison['rows']}
    previous = rows(OUT/'answers.jsonl')
    done={(r['case_id'],r['repeat'],r['mode']) for r in previous if r['status']=='completed'}
    client=paid_client(True)
    for cid,repeat,mode in read(OUT/'schedule.json'):
        if (cid,repeat,mode) in done or (cid,repeat,mode) in TERMINAL_ANSWER_KEYS:continue
        selected=selections[cid,mode]
        assert selected['status']=='selected'
        request=build_request(cases[cid],selected['selected'],CONFIG['answer_options'])
        started=time.perf_counter()
        try:
            response=client.responses.create(**request)
        except Exception as error:
            append(OUT/'answer_errors.jsonl',{'case_id':cid,'repeat':repeat,'mode':mode,
                'request_hash':digest(request),'error_type':type(error).__name__,
                'status_code':getattr(error,'status_code',None),'seconds':time.perf_counter()-started,
                'usage':None})
            raise RuntimeError('Answer API failed; safe metadata saved; completed calls preserved') from None
        record={'case_id':cid,'repeat':repeat,'mode':mode,'request_hash':digest(request),
            'status':response.status,'text':response.output_text,'response_id':response.id,
            'model':response.model,'service_tier':response.service_tier,
            'usage':response.usage.model_dump(),'answer_seconds':time.perf_counter()-started}
        append(OUT/'answers.jsonl',record)
        if response.status!='completed':raise RuntimeError('Incomplete answer; saved billed response')
        print('answered',len(done)+1,cid,mode,round(record['answer_seconds'],2),flush=True)
        done.add((cid,repeat,mode))


def grade():
    judge = module('pilot_judge',ROOT/'frozen/judge_reference.py')
    cases = {r['case']['id']:r for r in originals()}
    completed={(r['case_id'],r['repeat'],r['mode']) for r in rows(OUT/'grades.jsonl')}
    from openai import OpenAI
    client=OpenAI(timeout=120,max_retries=0)
    class Meter:
        def create(self,**kwargs):
            started=time.perf_counter()
            try:
                response=client.responses.create(**kwargs)
            except Exception as error:
                append(OUT/'judge_errors.jsonl',{'job':self.job,
                    'error_type':type(error).__name__,'status_code':getattr(error,'status_code',None),
                    'seconds':time.perf_counter()-started,'usage':None})
                raise RuntimeError('Judge API failed; completed grades preserved') from None
            append(OUT/'judge_calls.jsonl',{'job':self.job,'seconds':time.perf_counter()-started,
                'model':response.model,'service_tier':response.service_tier,
                'status':response.status,'usage':response.usage.model_dump(),'response_id':response.id})
            return response
    meter=Meter()
    evaluator=judge.Judge(OUT/'judge_cache',model='gpt-6-luna',client=SimpleNamespace(responses=meter))
    assert evaluator.reasoning_effort is None, 'Preserve original unset judge reasoning'
    for a in rows(OUT/'answers.jsonl'):
        key=(a['case_id'],a['repeat'],a['mode'])
        if key in completed or a['status']!='completed':continue
        c=cases[a['case_id']]['case']
        output={'text':a['text'],'queries':cases[a['case_id']]['output']['queries']}
        meter.job=key
        result=evaluator.evaluate('post_qa',c,output,judge.judge_material('post_qa',c,output),judge.judge_images('post_qa',c,DATA))
        append(OUT/'grades.jsonl',{'case_id':key[0],'repeat':key[1],'mode':key[2],**result})
        completed.add(key)
        print('graded',len(completed),key[0],key[2],result['verdicts']['correct']['pass'],flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('stage',choices=['retrieve','prepare','rank','answer','grade'])
    p.add_argument('--allow-paid',action='store_true')
    args=p.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    if args.stage!='prepare':
        if not args.allow_paid:raise RuntimeError('Explicit --allow-paid required')
        load_key()
    if args.stage=='retrieve':asyncio.run(retrieve())
    else:globals()[{'prepare':'build_bundle'}.get(args.stage,args.stage)]()
