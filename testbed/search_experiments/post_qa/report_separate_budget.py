"""Report only: original / interleave / pinned fact-5+episode-5 selector."""
import hashlib
import json
import math
import statistics as st
import subprocess
from collections import Counter
from budget_lab import read, write
from run_pilot import rows
from run_separate_budget import ROOT,OUT,SOURCE,prepare

MODES=('baseline','interleave','separate_5_5')
NAMES={'baseline':'A 기존 합계 5개','interleave':'B 번갈아 합계 5개','separate_5_5':'C Fact 5 + Episode 5'}
def kind(m):return 'episode' if m.get('source_episode_ids')==[m['id']] else 'fact'
def main():
    prepare()
    orig={r['case']['id']:r['case'] for r in read(SOURCE/'original_cases.json')}
    selections={(r['case_id'],r['mode']):r for r in read(SOURCE/'selection_comparison.json')['rows'] if r['mode'] in MODES}
    selections.update({(r['case_id'],r['mode']):r for r in read(OUT/'selection_comparison.json')['rows']})
    answers={(r['case_id'],r['mode']):r for r in rows(SOURCE/'answers.jsonl') if r['mode'] in MODES}
    answers.update({(r['case_id'],r['mode']):r for r in rows(OUT/'answers.jsonl') if r['status']=='completed'})
    grades={(r['case_id'],r['mode']):r for r in rows(SOURCE/'grades.jsonl') if r['mode'] in MODES}
    grades.update({(r['case_id'],r['mode']):r for r in rows(OUT/'grades.jsonl')})
    terminal={r['case_id'] for r in rows(OUT/'terminal_errors.jsonl')}
    assert len({cid for cid,mode in grades if mode=='separate_5_5'}|terminal)==100
    assert set(answers)==set(grades)
    retrieval=read(SOURCE/'retrieval.json')
    details=[];summary={}
    for mode in MODES:
        d=[]
        for cid in orig:
            s=selections[cid,mode];memories=s['selected']
            a=answers.get((cid,mode));g=grades.get((cid,mode))
            posts=sorted({x['name'] for m in memories for x in m.get('sources',[]) if x.get('name','').startswith('post_')})
            r={'case_id':cid,'mode':mode,'status':'graded' if g else 'ungraded',
               'correct':g['verdicts']['correct']['pass'] if g else None,
               'answers_question':g['verdicts']['answers_question']['pass'] if g else None,
               'no_stale_or_invented':g['verdicts']['no_stale_or_invented']['pass'] if g else None,
               'all_judge_pass':all(v['pass'] for v in g['verdicts'].values()) if g else None,
               **s['metrics'],'unique_post_count':len(posts),'unique_posts':posts,
               'fact_count':sum(kind(m)=='fact' for m in memories),'episode_count':sum(kind(m)=='episode' for m in memories)}
            for key in ('input_tokens','output_tokens','total_tokens'):
                r[key]=a['usage'][key] if a else None
            r['cached_tokens']=a['usage'].get('input_tokens_details',{}).get('cached_tokens',0) if a else None
            r['answer_seconds']=a['answer_seconds'] if a else None
            r['composed_seconds']=a['answer_seconds']+retrieval[cid]['seconds'] if a else None
            d.append(r)
        details+=d
        s={'scheduled':100,'graded':sum(x['status']=='graded' for x in d)}
        for key in ('correct','answers_question','no_stale_or_invented','all_judge_pass','required_all_present'):
            s[key]=sum(x[key] is True for x in d)
        for key in ('required_recall','selected_count','source_count','unique_post_count','fact_count','episode_count',
                    'input_tokens','output_tokens','total_tokens','cached_tokens','answer_seconds','composed_seconds'):
            s[key+'_mean']=st.mean(x[key] for x in d if x[key] is not None)
        seconds=sorted(x['answer_seconds'] for x in d if x['answer_seconds'] is not None)
        s['answer_seconds_median']=st.median(seconds);s['answer_seconds_p95']=seconds[math.ceil(.95*len(seconds))-1]
        s['failed_with_all_required_labels']=sum(x['correct'] is False and x['required_all_present'] for x in d)
        s['failed_without_all_required_labels']=sum(x['correct'] is False and not x['required_all_present'] for x in d)
        s['selected_count_distribution']=dict(sorted(Counter(x['selected_count'] for x in d).items()))
        summary[mode]=s
    paired={}
    for mode in MODES[:2]:
        paired[mode]={}
        for name,old,new in [('gained',False,True),('lost',True,False),('both_correct',True,True),('both_failed',False,False)]:
            paired[mode][name]=[cid for cid in orig if (cid,'separate_5_5') in grades and
                grades[cid,mode]['verdicts']['correct']['pass']==old and grades[cid,'separate_5_5']['verdicts']['correct']['pass']==new]
    groups={topic:{mode:sum(x['correct'] is True for x in details if x['mode']==mode and x['case_id'].split('@')[0]==topic)
                   for mode in MODES} for topic in sorted({cid.split('@')[0] for cid in orig})}
    from portable import verify_code
    shared={'packaged_experiment_sources':verify_code()}
    verify={'shared_tracked_diff_unchanged':shared,'archived_request_hashes_verified':200,
        'changed_only_selected_tool_outputs':True,'same_prompt_gold_judge':True,'new_graph_or_embedding_calls':0,
        'new_answer_calls':len(rows(OUT/'answers.jsonl')),'new_judge_calls':len(rows(OUT/'judge_calls.jsonl')),
        'cached_grades':sum(r.get('cached',False) for r in rows(OUT/'grades.jsonl')),
        'answer_errors':rows(OUT/'answer_errors.jsonl'),'judge_errors':rows(OUT/'judge_errors.jsonl'),
        'terminal_errors':rows(OUT/'terminal_errors.jsonl'),
        'reported_new_answer_tokens':sum(r['usage']['total_tokens'] for r in rows(OUT/'answers.jsonl')),
        'reported_new_judge_tokens':sum(r['usage']['total_tokens'] for r in rows(OUT/'judge_calls.jsonl'))}
    result={'summary':summary,'paired':paired,'by_topic':groups,'cases':details,'verification':verify}
    write(OUT/'results.json',result);write(OUT/'verification.json',verify)
    lines=['# 기억 선택 비교: 기존 / 번갈아 / Fact 5 + Episode 5','',
        '- 새 방식은 fix/backend-searching의 855cd61fd33e2a6ab2bf28a2b783e7b2c690bfcd select_budget 함수를 그대로 실행했다.',
        '- 20개 게시글 × 열람자 5명 = 100건, 각 1회. A/B 기존 답변·채점을 재사용하고 C만 새로 생성·채점했다.',
        '- 검색 질문·검색 후보·사진·본문·가족관계·질문 시점·QA 프롬프트·정답·채점 기준을 고정했다. 프롬프트 수정안 실험 결과는 섞지 않았다.',
        '- 답변: gpt-6-luna / service_tier=fast / reasoning.effort=none / max_output_tokens=700. 기존 채점 설정 유지.',
        '- Neo4j 재구축, 검색 판단, 검색 임베딩, reranker 호출은 하지 않았다. 공유 앱 코드는 수정하지 않았다.','',
        '| 지표 | A 기존 합계 5개 | B 번갈아 합계 5개 | C Fact 5 + Episode 5 |','|---|---:|---:|---:|']
    specs=[('정답 충족','correct','count'),('필수 근거 라벨 확보율','required_recall_mean','pct'),('필수 라벨 모두 확보','required_all_present','count'),
        ('오래된 정보·허구 없음','no_stale_or_invented','count'),('질문에 응답','answers_question','count'),('모든 채점 항목 통과','all_judge_pass','count'),
        ('평균 선택 Fact','fact_count_mean','num'),('평균 선택 Episode','episode_count_mean','num'),('평균 고유 출처 게시글','unique_post_count_mean','num'),
        ('평균 입력 토큰','input_tokens_mean','num'),('평균 출력 토큰','output_tokens_mean','num'),('평균 입력+출력 토큰','total_tokens_mean','num'),
        ('평균 캐시 입력 토큰','cached_tokens_mean','num'),('평균 답변 호출 시간(초)','answer_seconds_mean','num'),
        ('답변 시간 중앙값(초)','answer_seconds_median','num'),('답변 시간 p95(초)','answer_seconds_p95','num'),('검색+답변 합산 시간(초)','composed_seconds_mean','num')]
    for name,key,fmt in specs:
        def f(x):return f'{x}/100' if fmt=='count' else f'{100*x:.1f}%' if fmt=='pct' else f'{x:,.2f}'
        lines.append('| '+name+' | '+' | '.join(f(summary[m][key]) for m in MODES)+' |')
    lines+=['','## 사례 변화','']
    for m in MODES[:2]:
        p=paired[m];lines.append(f"- {NAMES[m]} → C: 오답→정답 {len(p['gained'])}건, 정답→오답 {len(p['lost'])}건.")
    for m in MODES:
        s=summary[m];lines.append(f"- {NAMES[m]}: 필수 라벨 모두 확보한 {s['required_all_present']}건 중 오답 {s['failed_with_all_required_labels']}건; 필수 라벨이 부족한 오답 {s['failed_without_all_required_labels']}건.")
    lines+=['','## 해석 범위','',
        '- 확보율은 정답 출처의 라벨 포함 여부다. 출처가 실제 필요한 내용을 모두 담았다는 의미는 아니다.',
        '- Fact/Episode 합계 최대 10개이며 고유 게시글 10개를 보장하지 않는다. 고유 게시글은 전달된 sources의 post 이름을 중복 제거해 계산했다.',
        '- 토큰은 최종 답변 호출의 입력(사진 포함)+출력이다. 검색 판단·임베딩·기억 적재·채점 비용은 비교 표 밖이다.',
        '- 답변 시간은 호출부터 완료까지다. 합산 시간은 기존 검색 시간을 공통으로 더한 값이며 앱 전체 지연 실측이 아니다.',
        '- A/B/C 실행 시점과 캐시가 달라 지연·비용 차이를 선택 방식만의 효과로 단정할 수 없다.',
        '- 1회 반복, 20개 주제의 열람자 변형 100건이다. 독립 100개 주제의 일반화 성능이나 통계적 유의성을 보장하지 않는다.',
        '- 기존 채점 입력의 관계·시간 누락 및 조건 해석 문제를 수정하지 않았다. 판정 주의 사례는 별도 검토하되 점수는 보정하지 않는다.',
        '- 오류 응답은 미채점으로 별도 기록하며 전체 예정 100건 기준 정답 수를 표시한다. 오류로 토큰 usage를 받지 못하면 비용은 확인 불가다.',
        '', '## 주제별 정답 (각 5건)','','| 주제 | A | B | C |','|---|---:|---:|---:|']
    lines += ['| '+topic+' | '+' | '.join(f"{r[m]}/5" for m in MODES)+' |' for topic,r in groups.items()]
    lines += ['','## 파일','','- CASES.md: 전체 질문·정답·세 방식 답변·채점 사유·C 선택 근거','- REVIEW.md: 개선 및 실패 사례 해석','- selection_comparison.json: C 선택 근거와 확보율','- manifest.json / verification.json: 재현 조건과 불변 검증','- qa_prompt.txt: 세 방식 공통 QA 프롬프트']
    (OUT/'RESULTS.md').write_text('\n'.join(lines)+'\n')
    detail=['# 전체 사례 대조','']
    for cid,c in orig.items():
        detail += [f'## {cid}','',f"- 작성자: {c['author_name']} / 열람자: {c['viewer_name']}",f"- 게시글: {c['caption']}",
            f"- 질문: {c['question']}",f"- 정답 기록: {json.dumps(c.get('reference'),ensure_ascii=False)}",f"- 이전 기록: {json.dumps(c.get('stale_reference'),ensure_ascii=False)}",'']
        for mode in MODES:
            g=grades.get((cid,mode));a=answers.get((cid,mode));s=selections[cid,mode]
            detail += [f"**{NAMES[mode]}**",'',a['text'] if a else 'API 오류/미완료로 답변 없음','',
                f"정답 판정: {g['verdicts']['correct'] if g else '미채점'}",f"근거 지표: {s['metrics']}",'']
        detail+=['<details><summary>C의 선택된 기억과 출처</summary>','','```json',json.dumps(selections[cid,'separate_5_5']['selected'],ensure_ascii=False,indent=2),'```','','</details>','']
    (OUT/'CASES.md').write_text('\n'.join(detail)+'\n')
    print(json.dumps({'summary':summary,'paired_counts':{m:{k:len(v) for k,v in p.items()} for m,p in paired.items()},'verification':verify},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
