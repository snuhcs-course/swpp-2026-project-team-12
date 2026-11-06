import json,statistics,math
from pathlib import Path
from collections import Counter
from run import ROOT,CFG,CASES,read,save,rows,verify_inputs
OUT=ROOT/'output'
def avg(xs):return statistics.mean(xs) if xs else None
def metrics(rs,gs):
 good=[r for r in rs if r['status']=='complete'];paired=[(r,gs[r['id']]) for r in good if r['id'] in gs]
 eligible=[(r,g) for r,g in paired if next(c for c in CASES if c['id']==r['case_id'])['answerability']=='answerable']
 negative=[(r,g) for r,g in paired if next(c for c in CASES if c['id']==r['case_id'])['answerability']=='unanswerable']
 update=[(r,g) for r,g in paired if next(c for c in CASES if c['id']==r['case_id'])['category']=='update_correction']
 citations=[(r,g) for r,g in eligible if r['cited_post_keys']]
 times=sorted(r['online_seconds'] for r in good)
 def tokens(r,key):return sum(x[key] for x in r['usage']['by_model_endpoint'] if x['endpoint']!='embedding')
 return {'tasks':len(rs),'complete':len(good),'errors':len(rs)-len(good),'graded':len(paired),'correct':sum(g['correct'] for r,g in paired),'accuracy':sum(g['correct'] for r,g in paired)/len(rs) if rs else None,'strict_accuracy':sum(g['correct'] and g['no_material_false_additions'] for r,g in paired)/len(rs) if rs else None,'retrieval_evidence_recall':avg([r['retrieval_evidence_recall'] for r,g in eligible]),'citation_id_recall':avg([r['citation_id_recall'] for r,g in eligible]),'citation_id_precision':avg([r['citation_id_precision'] for r,g in citations]),'semantic_citation_sufficiency':avg([g['citation_sufficient'] for r,g in eligible]),'supported_citation_precision':sum(len(set(g['supported_citation_keys'])) for r,g in citations)/sum(len(set(r['cited_post_keys'])) for r,g in citations) if citations else None,'empty_citations_answerable':sum(not r['cited_post_keys'] for r,g in eligible),'memory_update_error_rate':avg([g['memory_update_error'] for r,g in update]),'abstention_accuracy':avg([g['correct'] and g['abstained'] for r,g in negative]),'unanswerable_empty_citations':avg([not r['source_episode_ids'] for r,g in negative]),'input_tokens':avg([tokens(r,'input_tokens') for r in good]),'output_tokens':avg([tokens(r,'output_tokens') for r in good]),'cached_input_tokens':avg([tokens(r,'cached_input_tokens') for r in good]),'generation_tokens':avg([r['usage']['observed_generation_tokens'] for r in good]),'embedding_tokens':avg([r['usage']['observed_embedding_tokens'] for r in good]),'mean_seconds':avg(times),'p95_seconds':times[math.ceil(.95*len(times))-1] if times else None,'answer_seconds':avg([r['timings'].get('answer',0) for r in good]),'search_seconds':avg([r['timings'].get('search',0) for r in good])}
def main(phase):
 rs=[r for n in CFG['sizes'] for r in rows(OUT/f'history_{n}/{phase}.jsonl')];gs={g['id']:g for g in read(OUT/f'{phase}_grades.json')}
 cells={f'{n}_{m}':metrics([r for r in rs if r['size']==n and r['mode']==m],gs) for n in CFG['sizes'] for m in ['full_history','graphiti'] if any(r['size']==n for r in rs)}
 save(OUT/f'{phase}_metrics.json',cells)
 def pc(v):return f'{v*100:.1f}%' if v is not None else '—'
 def num(v):return f'{v:,.2f}' if v is not None else '—'
 lines=[f'# 가족 추억 찾기 — {"본실험" if phase=="full" else "예비 실험"} 결과','',f"앱 `{CFG['app_commit'][:7]}`. Luna Fast / reasoning none / 출력 1,200토큰. 기존 사진 설명·그래프를 재사용하며 공유 앱 코드는 변경하지 않았다.",'',f"완료 {sum(r['status']=='complete' for r in rs)}/{len(rs)}, 채점 {len(gs)}. 본실험 계획 540건, 예비 계획 20건. 방식 이름을 가린 Luna Fast 의미 채점이며 독립 사람 채점은 아직 없다.",'','| 기록 수 | 방식 | Answer Accuracy | Evidence Recall | Citation Sufficiency | Tokens/질문 | 평균 시간 | P95 시간 |','|---:|---|---:|---:|---:|---:|---:|---:|']
 for k,m in cells.items():
  n,mode=k.split('_',1);lines.append(f"| {n} | {mode} | {pc(m['accuracy'])} ({m['correct']}/{m['tasks']}) | {pc(m['retrieval_evidence_recall'])} | {pc(m['semantic_citation_sufficiency'])} | {num(m['generation_tokens'])} | {num(m['mean_seconds'])} s | {num(m['p95_seconds'])} s |")
 lines += ['','## Graphiti / Full History','', '| 기록 수 | 정확도 차이 | 생성 토큰 비율 | 시간 비율 |','|---:|---:|---:|---:|']
 for n in CFG['sizes']:
  if f'{n}_graphiti' not in cells:continue
  g=cells[f'{n}_graphiti'];f=cells[f'{n}_full_history']
  lines.append(f"| {n} | {(g['accuracy']-f['accuracy'])*100:+.1f}%p | {g['generation_tokens']/f['generation_tokens']:.3f}× | {g['mean_seconds']/f['mean_seconds']:.3f}× |")
 lines += ['','## 출처와 오류','', '| 기록 수 | 방식 | Citation ID Recall | Supported Citation Precision | Memory Update Error | Abstention Accuracy | 정보 없음에서 빈 출처 |','|---:|---|---:|---:|---:|---:|---:|']
 for k,m in cells.items():
  n,mode=k.split('_',1);lines.append(f"| {n} | {mode} | {pc(m['citation_id_recall'])} | {pc(m['supported_citation_precision'])} | {pc(m['memory_update_error_rate'])} | {pc(m['abstention_accuracy'])} | {pc(m['unanswerable_empty_citations'])} |")
 lines += ['','## 유형별 정확도','', '| 유형 | Full History | Graphiti |','|---|---:|---:|']
 for cat in ['single_fact','update_correction','entity_disambiguation','multi_record','unanswerable']:
  ids={c['id'] for c in CASES if c['category']==cat}; vals=[]
  for mode in ['full_history','graphiti']:
   subset=[r for r in rs if r['case_id'] in ids and r['mode']==mode];m=metrics(subset,gs);vals.append(f"{m['correct']}/{m['tasks']} ({pc(m['accuracy'])})")
  lines.append('| '+cat+' | '+' | '.join(vals)+' |')
 lines += ['','## 측정 범위와 해석','', '- Evidence Recall은 충분 근거 조합의 게시글 ID 확보율이다. 정보 없음 4문항은 제외한다. 의미 근거 충분성과 동일하지 않다.', '- Citation Sufficiency는 최종 표시 출처가 정답을 충분히 지지하는지 의미 채점한 비율이다. Citation ID Recall은 사전 정답표 기준이며 대체 근거 인정 여부와 차이가 날 수 있다.', '- Supported Citation Precision은 답변 가능한 문항에서 실제 표시한 출처 중 관련 사실을 지지하는 출처의 비율이다. 빈 출처는 precision 분모에서 제외하고 sufficiency/recall에서 실패로 반영한다.', '- 생성 토큰은 온라인 입력+출력이며 캐시 입력도 포함한다. 임베딩·채점은 별도. 실청구 비용 또는 전체 서비스 비용으로 해석하지 않는다.', '- 시간은 문맥 조립·검색·답변 완료까지 포함하며 HTTP·큐·UI·TTS·출처 카드 직렬화는 제외한다. 최초 호출을 제외하지 않았다.', '- Full에 역사 사진을 재전송하지 않고 동일한 동결 설명을 제공했다. 사진 이해 품질과 최신 construction 품질을 새로 측정한 실험은 아니다.', '- 한 합성 가족·30문항이다. 반복은 독립 질문 수를 늘리지 않으며 새로운 문항 구성이므로 과거 Post QA 정확도와 직접 비교하지 않는다.', '- 초기 예비 환경 오류 1건(임베딩 35토큰)은 별도 보존 후 환경만 복구했다. 본실험과 예비의 정상 결과에 합산하지 않는다.', '- 수치에 맞춰 정답·질문·프롬프트를 사후 변경하지 않았다. 결과의 합격 기준을 임의로 설정하지 않았다.']
 lines += ['', '채점 주의: Memory Update Error 자동 판정은 수동 대조와 불일치하여 해석을 보류한다. reports/ANALYSIS.md 및 reports/RESULTS.md의 검수 주의사항을 함께 읽는다.']
 (OUT/('RESULTS.md' if phase=='full' else 'PILOT.md')).write_text('\n'.join(lines)+'\n')
 failures=['# 실패 사례 — 가족 추억 찾기','', '정답 실패 또는 표시 출처가 충분하지 않은 응답. 정보 없음의 불필요한 출처는 별도로 포함. 원시 채점은 보존했다.','']
 allcases=['# 전체 질문·답변·출처','']
 byid={c['id']:c for c in CASES}
 for r in sorted(rs,key=lambda x:(x['case_id'],x['size'],x['mode'],x['repeat'])):
  if r['id'] not in gs:continue
  g=gs[r['id']];c=byid[r['case_id']]
  block=[f"## {r['id']}",f"- 질문: {c['question']}",f"- 정답: {c['expected_answer']}",f"- 답변: {r['answer']}",f"- 표시 게시글: {r['cited_post_keys']}",f"- 정답 근거 조합: {c['evidence_sets']}",f"- 검색 근거 확보율: {r['retrieval_evidence_recall']}",f"- Correct: {g['correct']}; Citation Sufficient: {g['citation_sufficient']}",f"- 채점: {g['reason']}"]
  if not g['correct'] or (c['answerability']=='answerable' and not g['citation_sufficient']) or (c['answerability']=='unanswerable' and r['source_episode_ids']):
   for k,v in c['evidence_captions'].items():block.append(f'  - {k}: {v}')
   failures+=block+['']
  allcases+=block+['']
 (OUT/f'{phase.upper()}_FAILURES.md').write_text('\n'.join(failures)+'\n');(OUT/f'{phase.upper()}_CASES.md').write_text('\n'.join(allcases)+'\n')
 verify_inputs();print(json.dumps(cells,ensure_ascii=False,indent=2))
if __name__=='__main__':
 import sys;main(sys.argv[1])
