"""Read-only family_history benchmark; all app modules imported unchanged from git archive."""
import asyncio,hashlib,json,os,random,shutil,subprocess,sys,time
from pathlib import Path
from datetime import datetime
from unittest.mock import patch,AsyncMock
ROOT=Path(__file__).resolve().parent; REPO=ROOT.parents[2]; WORK=REPO
LEGACY=REPO/'testbed/memoryqa_scaling';OLD=ROOT/'.inputs'
sys.path.insert(0,str(LEGACY))
from lib.common import read,save,digest,sha,dataset
from lib.graphs import canonical
from lib.original.usage import capture,instrument_sdk,totals
from lib.read_only_database import read_only_database_scope
CFG=read(ROOT/'config.json');CASES=read(ROOT/'cases.json')
def rows(p):return [json.loads(s) for s in p.read_text().splitlines()] if p.exists() else []
def append(p,x):
 p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('a') as f:f.write(json.dumps(x,ensure_ascii=False)+'\n');f.flush()
def verify_inputs():
 lock=read(ROOT/'runtime_lock.json')
 for p,h in lock['inputs'].items():assert sha(ROOT/p)==h,p
 for p,h in lock['app_files'].items():assert sha(ROOT/p)==h,p
 for p,h in lock['dataset_files'].items():assert sha(REPO/p)==h,p
 return digest(lock)
def setup(size,paid):
 from importlib.metadata import version
 assert version('graphiti-core')=='0.31.1', 'graphiti-core version mismatch'
 key=os.environ.get('OPENAI_API_KEY') if paid else 'offline-no-api'
 if not key:raise RuntimeError('Set OPENAI_API_KEY in the environment')
 password=os.environ.get('NEO4J_PASSWORD')
 if not password:raise RuntimeError('Set NEO4J_PASSWORD for the isolated restored graph')
 out=ROOT/f'output/history_{size}';out.mkdir(parents=True,exist_ok=True)
 db=out/'test.sqlite3'
 if not db.exists():shutil.copy2(OLD/f'history_{size}/test.sqlite3',db)
 env={'DJANGO_SETTINGS_MODULE':'configs.settings','DJANGO_DB_PATH':str(db),'DJANGO_MEDIA_ROOT':str(LEGACY),'DJANGO_DEBUG':'1','DJANGO_SECRET_KEY':'family-history-eval-only','DJANGO_ALLOWED_HOSTS':'testserver,localhost','OPENAI_API_KEY':key,'NEO4J_URI':os.environ.get('NEO4J_URI','bolt://127.0.0.1:7690'),'NEO4J_USER':os.environ.get('NEO4J_USER','neo4j'),'NEO4J_PASSWORD':password,'GRAPHITI_MODEL':CFG['model'],'GRAPHITI_REASONING_EFFORT':'','GRAPHITI_TELEMETRY_ENABLED':'false'}
 for g in ['DEFAULT','SUMMARY','ANSWER','QUERY','STT']:
  env.update({f'{g}_AI_MODEL':CFG['model'],f'{g}_AI_SERVICE_TIER':'fast',f'{g}_AI_REASONING_EFFORT':'none'})
 os.environ.update(env);sys.path.insert(0,str(ROOT/'.runtime/backend'))
 import django;django.setup()
 from django.conf import settings
 assert str(settings.DATABASES['default']['NAME'])==str(db)
 return out
async def graph_state(graph,size):
 group=f'family_{832000+size}'
 ns,_,_=await graph.driver.execute_query('MATCH (n {group_id:$g}) RETURN properties(n) AS p,labels(n) AS labels ORDER BY n.uuid',g=group)
 es,_,_=await graph.driver.execute_query('MATCH (n {group_id:$g})-[r]->(m) RETURN n.uuid AS a,m.uuid AS b,type(r) AS kind,properties(r) AS p ORDER BY a,b,kind,r.uuid',g=group)
 return canonical([dict(n) for n in ns],[dict(e) for e in es])
async def context_sources(graph,size):
 rs,_,_=await graph.driver.execute_query('MATCH (e:Episodic {group_id:$g}) RETURN e.uuid AS id,e.name AS name,e.content AS text,toString(e.valid_at) AS recorded_at ORDER BY e.valid_at,e.name',g=f'family_{832000+size}')
 sources=[dict(r) for r in rs];fixture=read(OLD/f'history_{size}/fixture.json');data=dataset(size)
 mapping={f'post_{v}':k for k,v in fixture['post_ids'].items() if k in data['memory']}
 desc={r['post_key']:r['description'] for r in read(OLD/'common/descriptions.json')['records']}
 reg=read(OLD/f'history_{size}/registry.json')
 assert len(sources)==size+1
 assert {s['name'] for s in sources}==set(mapping)|{reg['name']}
 for s in sources:
  assert datetime.fromisoformat(s['recorded_at'])<datetime.fromisoformat(CASES[0]['asked_at'])
  if s['name'] in mapping:
   k=mapping[s['name']];p=data['memory'][k]
   assert s['text']==f"작성자: {data['people'][p['author_key']]}\n상세 설명: {desc[k]}"
  else:assert s['text']==reg['text']
 return sources,{s['id']:mapping.get(s['name'],'REGISTRY') for s in sources}
def recall(c,keys):
 return max((len(set(s)&set(keys))/len(s) for s in c['evidence_sets']),default=None)
def resolve_posts(result,size):
 from apps.searching.evidence import evidence_posts
 from apps.families.models import FamilyRoom
 from django.test import RequestFactory
 room=FamilyRoom.objects.get(pk=832000+size)
 req=RequestFactory().get('/api/searching/');req.user=room.owner
 return evidence_posts(result,room,req)
async def main(size,phase,paid):
 signature=verify_inputs();out=setup(size,paid)
 from integrations.ai_workers.graphiti_client import create_graphiti,close_graphiti
 from integrations.ai_workers.searching_graphiti import search_many
 from integrations.ai import flow,history_evidence,prompts
 from integrations.ai.options import model_options
 from asgiref.sync import sync_to_async
 from openai import AsyncOpenAI
 graph=create_graphiti()
 try:
  with read_only_database_scope():
   before=digest(await graph_state(graph,size));expected=read(OLD/f'history_{size}/graph_seed.json')['fingerprint'];assert before==expected,'graph changed'
   sources,mapping=await context_sources(graph,size)
   save(out/'sources.json',sources)
   assert flow.two_way_or_three_way('family_history')==2
   assert model_options('ANSWER')=={'model':'gpt-6-luna','service_tier':'fast','reasoning':{'effort':'none'}}
   if phase=='check':
    with patch.object(graph.embedder,'create',new=AsyncMock(return_value=[0.001]*1024)):
     search_check=await search_many(graph,832000+size,['모모 아침밥'])
    assert search_check and search_check[0]['memories']
    # Test actual app evidence mapper with known valid, duplicate, and foreign IDs.
    sample=next(s for s in sources if mapping[s['id']]!='REGISTRY')
    fake={'source_episode_ids':[sample['id'],'not-allowed'],'memories':[{'sources':[sample]}]}
    parsed=history_evidence.parse_answer(json.dumps({'text':'검증','source_episode_ids':[sample['id'],sample['id'],'not-allowed']}),fake['memories'])
    assert parsed['source_episode_ids']==[sample['id']]
    linked=await sync_to_async(resolve_posts)({**fake,**parsed},size)
    assert len(linked['evidence_posts'])==1 and linked['evidence_kind']=='cited'
    save(out/'preflight.json',{'passed':True,'graph_fingerprint':before,'sources':len(sources),'history':size,'graph_unchanged':True,'actual_evidence_mapper_checked':True,'api_calls':0,'signature':signature})
    print('preflight',size,'PASS',flush=True);return
   assert paid
   assert read(out/'preflight.json')['passed']
   cases=CASES if phase=='full' else [c for c in CASES if c['id'] in CFG['pilot_ids']]
   tasks=[{'id':f"{phase}-{size}-{c['id']}-{mode}-{rep}",'case':c,'mode':mode,'repeat':rep} for rep in range(1,(CFG['repetitions'] if phase=='full' else 1)+1) for c in cases for mode in ['full_history','graphiti']]
   random.Random(CFG['seed']+size+(0 if phase=='full' else 1)).shuffle(tasks)
   save(out/f'{phase}_schedule.json',[{k:v for k,v in t.items() if k!='case'} for t in tasks])
   path=out/f'{phase}.jsonl';done={r['id'] for r in rows(path)}
   assert len(done)==len(rows(path))
   with instrument_sdk():
    for t in tasks:
     if t['id'] in done:continue
     c=t['case'];row={k:v for k,v in t.items() if k!='case'};row.update(case_id=c['id'],size=size,question=c['question'],signature=signature)
     requests=[];timings={};started=time.perf_counter()
     with capture(lambda ep,kw: requests.append({'endpoint':ep,'request':kw}) if ep.startswith('responses') else None) as calls:
      try:
       if t['mode']=='graphiti':
        async def search(qs):return await search_many(graph,832000+size,qs)
        with patch.object(flow.timezone,'now',return_value=datetime.fromisoformat(c['asked_at'])):
         result=await flow.answer_with_memory(search,c['question'],'family_history',timings=timings)
       else:
        # Same instructions/format; all historical sources, no current post and no extracted facts.
        memories=[{'id':s['id'],'sources':[s]} for s in sources]
        started_assembly=time.perf_counter()
        payload=json.dumps({'질문':c['question'],'현재 시각':c['asked_at'],'기록':{'facts':[],'sources':sources}},ensure_ascii=False)
        timings['assembly']=time.perf_counter()-started_assembly;ts=time.perf_counter()
        async with AsyncOpenAI(api_key=os.environ['OPENAI_API_KEY'],timeout=60,max_retries=1) as client:
         resp=await client.responses.create(**model_options('ANSWER'),instructions=prompts.HISTORY_INSTRUCTIONS+history_evidence.INSTRUCTIONS,input=payload,max_output_tokens=1200,store=False,text=history_evidence.ANSWER_FORMAT)
        timings['answer']=time.perf_counter()-ts
        assert resp.status=='completed' and resp.output_text.strip(),'incomplete response'
        result={**history_evidence.parse_answer(resp.output_text,memories),'memories':memories,'query':c['question']}
       row['online_seconds']=time.perf_counter()-started
       retrieved={s['id']:s for m in result['memories'] for s in m.get('sources',[])}
       assert all(k in mapping for k in retrieved),'foreign source'
       for k,s in retrieved.items():
        original=next(x for x in sources if x['id']==k)
        assert all(s[f]==original[f] for f in ['id','name','text']) and datetime.fromisoformat(s['recorded_at'].replace('Z','+00:00'))==datetime.fromisoformat(original['recorded_at'].replace('Z','+00:00')),'source modified'
       cited=result['source_episode_ids'];linked=await sync_to_async(resolve_posts)(result,size)
       row.update(status='complete',answer=result['text'],source_episode_ids=cited,retrieved_sources=list(retrieved.values()),retrieved_post_keys=sorted({mapping[k] for k in retrieved if mapping[k]!='REGISTRY'}),cited_post_keys=[mapping[k] for k in cited if mapping[k]!='REGISTRY'],evidence_posts=linked['evidence_posts'],evidence_kind=linked['evidence_kind'])
       expected_ids=[int(retrieved[k]['name'][5:]) for k in cited if mapping[k]!='REGISTRY']
       actual=[x['id'] for x in linked['evidence_posts']]
       assert actual==expected_ids,(actual,expected_ids)
       row['retrieval_evidence_recall']=recall(c,row['retrieved_post_keys']);row['citation_id_recall']=recall(c,row['cited_post_keys'])
       row['citation_id_precision']=len(set(row['cited_post_keys']) & {k for s in c['evidence_sets'] for k in s})/len(set(row['cited_post_keys'])) if row['cited_post_keys'] else None
      except Exception as e:
       row.update(status='error',error_type=type(e).__name__,error_code=getattr(e,'code',None),error_details=repr(e),online_seconds=time.perf_counter()-started)
     row.update(calls=calls,usage=totals(calls),timings=timings,requests=requests)
     append(path,row);done.add(t['id']);print(phase,size,len(done),'/',len(tasks),row['status'],flush=True)
     if row['status']!='complete':raise RuntimeError(f"Stopped; saved {t['id']} {row['error_type']} {row.get('error_code')}")
   after=digest(await graph_state(graph,size));assert after==before
   verify_inputs();save(out/f'{phase}_integrity.json',{'before':before,'after':after,'graph_unchanged':True,'shared_app_unchanged':True,'completed':len(done),'signature':signature})
 finally:await close_graphiti(graph)
if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('phase',choices=['check','pilot','full']);p.add_argument('--size',type=int,default=100,choices=[100,200,300]);p.add_argument('--allow-paid',action='store_true');a=p.parse_args()
 if a.phase!='check' and not a.allow_paid:p.error('explicit --allow-paid required')
 asyncio.run(main(a.size,a.phase,a.allow_paid))
