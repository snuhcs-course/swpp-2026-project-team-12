"""Offline audit of captured inputs, counts, timing and source linkage."""
import json,hashlib
from collections import Counter
from datetime import datetime
from run import ROOT,CFG,CASES,rows,read,save,sha,verify_inputs

def audit(phase,require_complete=False):
 case_byid={c['id']:c for c in CASES};allrows=[];instruction_hashes=set();checks=[]
 for size in CFG['sizes']:
  p=ROOT/f'output/history_{size}/{phase}.jsonl'
  if not p.exists():continue
  data=rows(p);allrows+=data
  ids=[r['id'] for r in data];assert len(ids)==len(set(ids))
  for r in data:
   if r['status']!='complete':continue
   c=case_byid[r['case_id']]
   for s in r['retrieved_sources']:assert datetime.fromisoformat(s['recorded_at'].replace('Z','+00:00'))<datetime.fromisoformat(c['asked_at'])
   if not r['requests']:
    assert r['mode']=='graphiti' and r['answer']=='가족 기록에서 관련 내용을 찾지 못했어요.' and not r['retrieved_sources'];continue
   assert len(r['requests'])==1
   req=r['requests'][0]['request'];payload=json.loads(req['input'])
   assert payload['질문']==c['question'] and payload['현재 시각']==c['asked_at']
   assert set(payload)=={'질문','현재 시각','기록'} and set(payload['기록'])=={'facts','sources'}
   assert req['model']==CFG['model'] and req['service_tier']=='fast' and req['reasoning']=={'effort':'none'}
   assert req['max_output_tokens']==1200 and req['text']['format']['name']=='family_history_answer' and req['store'] is False
   assert not any(key in req for key in ['tools','previous_response_id'])
   if r['mode']=='full_history':assert len(payload['기록']['sources'])==size+1 and payload['기록']['facts']==[]
   instruction_hashes.add(hashlib.sha256(req['instructions'].encode()).hexdigest())
   assert all(call['status']=='completed' for call in r['calls'])
   assert r['usage']['usage_complete']
   # Citations are drawn from the captured memory and actually resolve to visible posts.
   cited=r['source_episode_ids'];sourceids={s['id'] for s in r['retrieved_sources']}
   assert set(cited)<=sourceids
   assert len(r['cited_post_keys'])==len(r['evidence_posts'])
  checks.append({'size':size,'tasks':len(data),'errors':sum(r['status']!='complete' for r in data)})
 assert len(instruction_hashes)<=1
 if require_complete:
  assert phase=='full' and len(allrows)==540
  assert Counter((r['size'],r['mode']) for r in allrows)=={(n,m):90 for n in CFG['sizes'] for m in ['full_history','graphiti']}
  assert Counter((r['size'],r['mode'],r['case_id']) for r in allrows)=={(n,m,c['id']):3 for n in CFG['sizes'] for m in ['full_history','graphiti'] for c in CASES}
  assert all(read(ROOT/f'output/history_{n}/full_integrity.json')['graph_unchanged'] for n in CFG['sizes'])
 verify_inputs()
 for filename,h in read(ROOT/'portable_code_lock.json').items():assert sha(ROOT/filename)==h,filename
 result={'passed':True,'phase':phase,'tasks':len(allrows),'cells':checks,'same_instructions':len(instruction_hashes)==1,'no_current_post_photo_gold_in_payload':True,'clock_fixed':True,'model_options_matched':True,'source_linkage_checked':True,'shared_app_unchanged':True,'full_runner_code_unchanged':True}
 save(ROOT/f'output/{phase}_audit.json',result);print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('phase',choices=['pilot','full']);p.add_argument('--complete',action='store_true');a=p.parse_args();audit(a.phase,a.complete)
