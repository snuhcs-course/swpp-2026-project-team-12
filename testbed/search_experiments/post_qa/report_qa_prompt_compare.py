"""Paired report; never modify answers, gold, or judge verdicts."""
import hashlib
import json
import statistics as st
import subprocess
from budget_lab import read, write
from run_pilot import rows
from run_qa_prompt_compare import ROOT, OUT, SOURCE, prepare

def main():
    prepare()
    orig={r['case']['id']:r['case'] for r in read(SOURCE/'original_cases.json')}
    sels={r['case_id']:r for r in read(SOURCE/'selection_comparison.json')['rows'] if r['mode']=='interleave'}
    retrieval=read(SOURCE/'retrieval.json')
    answers={'A':{a['case_id']:a for a in rows(SOURCE/'answers.jsonl') if a['mode']=='interleave'},
             'B':{a['case_id']:a for a in rows(OUT/'answers.jsonl') if a['status']=='completed'}}
    grades={'A':{a['case_id']:a for a in rows(SOURCE/'grades.jsonl') if a['mode']=='interleave'},
            'B':{a['case_id']:a for a in rows(OUT/'grades.jsonl')}}
    terminal=rows(OUT/'terminal_errors.jsonl')
    assert set(answers['B'])==set(grades['B'])
    assert len(set(answers['B'])|{a['case_id'] for a in terminal})==100
    details=[];summary={}
    for arm in ('A','B'):
        d=[]
        for cid,a in answers[arm].items():
            verdict=grades[arm][cid]['verdicts'];usage=a['usage']
            r={'case_id':cid,'arm':arm,'correct':verdict['correct']['pass'],
               'answers_question':verdict['answers_question']['pass'],'no_stale_or_invented':verdict['no_stale_or_invented']['pass'],
               'all_judge_pass':all(v['pass'] for v in verdict.values()),**sels[cid]['metrics'],
               'input_tokens':usage['input_tokens'],'output_tokens':usage['output_tokens'],'total_tokens':usage['total_tokens'],
               'cached_tokens':usage.get('input_tokens_details',{}).get('cached_tokens',0),
               'reasoning_tokens':usage.get('output_tokens_details',{}).get('reasoning_tokens',0),
               'answer_seconds':a['answer_seconds'],'composed_seconds':a['answer_seconds']+retrieval[cid]['seconds']}
            d.append(r)
        details+=d
        summary[arm]={'scheduled':100,'graded':len(d)}
        for k in ('correct','answers_question','no_stale_or_invented','all_judge_pass','required_all_present'):
            summary[arm][k]=sum(r[k] is True for r in d)
        for k in ('required_recall','input_tokens','output_tokens','total_tokens','cached_tokens','reasoning_tokens','answer_seconds','composed_seconds'):
            summary[arm][k+'_mean']=st.mean(r[k] for r in d)
        times=sorted(r['answer_seconds'] for r in d)
        summary[arm]['answer_seconds_median']=st.median(times)
        summary[arm]['answer_seconds_p95']=times[max(0,__import__('math').ceil(.95*len(times))-1)]
        summary[arm]['failed_with_all_required_labels']=sum(r['required_all_present'] and not r['correct'] for r in d)
    common=set(grades['A'])&set(grades['B'])
    pairs={name:sorted(cid for cid in common if grades['A'][cid]['verdicts']['correct']['pass']==old and grades['B'][cid]['verdicts']['correct']['pass']==new)
           for name,old,new in [('gained',False,True),('lost',True,False),('both_correct',True,True),('both_failed',False,False)]}
    groups={}
    for topic in sorted({cid.split('@')[0] for cid in orig}):
        groups[topic]={arm:sum(g['verdicts']['correct']['pass'] for cid,g in grades[arm].items() if cid.split('@')[0]==topic) for arm in ('A','B')}
    from portable import verify_code
    shared={'packaged_experiment_sources':verify_code()}
    verify={'shared_tracked_diff_unchanged':shared,'same_requests_except_instructions':100,'same_gold_and_judge':True,
            'new_answer_calls':len(rows(OUT/'answers.jsonl')),'new_judge_calls':len(rows(OUT/'judge_calls.jsonl')),
            'cached_grades':sum(g.get('cached',False) for g in grades['B'].values()),
            'answer_errors':rows(OUT/'answer_errors.jsonl'),'judge_errors':rows(OUT/'judge_errors.jsonl'),'terminal':terminal,
            'reported_new_answer_tokens':sum(a['usage']['total_tokens'] for a in rows(OUT/'answers.jsonl')),
            'reported_new_judge_tokens':sum(a['usage']['total_tokens'] for a in rows(OUT/'judge_calls.jsonl'))}
    write(OUT/'results.json',{'summary':summary,'paired':pairs,'by_topic':groups,'cases':details,'verification':verify})
    write(OUT/'verification.json',verify)
    a,b=summary['A'],summary['B']
    lines=['# QA 프롬프트 비교: 번갈아 선택 고정','',
           '- 같은 20개 게시글 × 열람자 5명 = 100건, 1회. A는 기존 100건과 채점을 재사용하고 B만 새로 생성·채점했다.',
           '- 검색 질문·사진·본문·관계·질문 시점·선택된 기억 5개·평가셋·정답·채점 기준은 동일하다. 100개 기존 요청 해시를 대조했다.',
           '- 답변 모델: gpt-6-luna, service_tier=fast, reasoning.effort=none, max_output_tokens=700. 채점 모델·기본 설정도 기존과 동일하다.',
           '- 변경: 최종 QA 규칙을 수정하고, 최종 응답 호출에서 검색 질문 생성 지시를 제외했다. 검색이나 추가 LLM 호출은 하지 않았다.','',
           '| 지표 | A 기존 QA | B 수정 QA |','|---|---:|---:|']
    for name,key,fmt in [('정답 충족','correct','count'),('질문에 응답','answers_question','count'),('오래된 정보·허구 없음','no_stale_or_invented','count'),
                         ('모든 채점 항목 충족','all_judge_pass','count'),('필수 근거 라벨 확보율','required_recall_mean','pct'),
                         ('필수 라벨 모두 확보한 사례 중 오답','failed_with_all_required_labels','subset'),
                         ('평균 입력 토큰','input_tokens_mean','num'),('평균 출력 토큰','output_tokens_mean','num'),
                         ('평균 입력+출력 토큰','total_tokens_mean','num'),('평균 답변 호출 시간(초)','answer_seconds_mean','sec'),
                         ('답변 시간 중앙값(초)','answer_seconds_median','sec'),('답변 시간 p95(초)','answer_seconds_p95','sec'),
                         ('검색+답변 합산 시간(초)','composed_seconds_mean','sec')]:
        def f(v):
            if fmt=='count':return f'{v}/100'
            if fmt=='pct':return f'{v*100:.1f}%'
            if fmt=='subset':return f'{v}/71'
            return f'{v:,.2f}'
        lines.append(f'| {name} | {f(a[key])} | {f(b[key])} |')
    lines += ['',f"- 오답→정답 {len(pairs['gained'])}건, 정답→오답 {len(pairs['lost'])}건, 양쪽 정답 {len(pairs['both_correct'])}건, 양쪽 오답 {len(pairs['both_failed'])}건.",
              '', '## 해석 범위','',
              '- 근거 확보율은 출처의 정답 라벨 포함 여부다. 그 출처가 실제 필요한 문장을 담았는지까지 보장하지 않는다. 선택은 같으므로 검색 성능 개선 실험이 아니다.',
              '- 최종 답변 호출 토큰은 입력+출력이며 이미지 입력을 포함한다. 검색 판단·임베딩·기억 적재·채점 비용은 비교 표에 포함하지 않는다.',
              '- 검색+답변 시간은 기존 검색 시간을 양쪽에 동일하게 더한 값이다. 새로 측정한 앱 전체 지연이 아니다. A와 B는 다른 시간에 실행되어 서버·캐시 차이가 영향을 줄 수 있다.',
              '- 기존 실패를 참고해 만든 수정안의 개발셋 비교다. 20개 게시글의 열람자 변형 100건으로, 독립적인 100개 주제나 미공개 평가셋 성능을 뜻하지 않는다.',
              '- 평가 질문·정답·기존 채점 입력의 시간/관계 정보 누락 문제는 수정하지 않았다. 최종 규칙 수정과 검색 지시 제거를 묶어 비교했으므로 개별 수정 효과는 분리할 수 없다.',
              '- 공유 앱 코드는 변경하지 않았다. 유료 호출 오류 및 토큰은 verification.json에 별도 기록한다. 응답 없는 오류의 토큰은 확인할 수 없다.',
              '', '## 주제별 정답 (각 5건)','','| 주제 | A | B |','|---|---:|---:|']
    for topic,r in groups.items():lines.append(f"| {topic} | {r['A']}/5 | {r['B']}/5 |")
    lines+=['','## 파일','','- prompt_A.txt / prompt_B.txt: 최종 호출 프롬프트 전후','- CASES.md: 질문·선택 근거·정답·양쪽 답변·판정 사유','- answers.jsonl / grades.jsonl: B 원본 로그','- manifest.json / verification.json: 고정 조건과 검증 결과']
    lines += ['', '사례별 해석과 채점 주의사항은 [REVIEW.md](REVIEW.md)를 참고한다.',
              f"A 평균 캐시 입력 {a['cached_tokens_mean']:,.0f}토큰, B {b['cached_tokens_mean']:,.0f}토큰이므로 총 토큰 감소율을 비용 절감률로 해석하지 않는다."]
    (OUT/'RESULTS.md').write_text('\n'.join(lines)+'\n')
    report=['# QA 비교 사례','', '기존 정답과 채점 기준을 유지한 원본 대조 기록. 라벨 확보와 실제 정보 충분성은 구분해야 한다.','']
    for group in ('gained','lost','both_failed','both_correct'):
        report += [f'## {group} ({len(pairs[group])})','']
        for cid in pairs[group]:
            c=orig[cid]
            report += [f'### {cid}','',f"- 작성자: {c['author_name']} / 질문자: {c['viewer_name']}",
                       f"- 게시글: {c['caption']}",f"- 질문: {c['question']}",
                       f"- 정답 기록: {c.get('reference')}",f"- 걸러야 할 기록: {c.get('stale_reference')}",
                       f"- 필수 라벨: {c.get('required_memories')}",f"- 선택 지표: {sels[cid]['metrics']}",'']
            for arm in ('A','B'):
                report += [f"**{arm} 답변**: {answers[arm][cid]['text']}",'',
                           f"정답 판정: {grades[arm][cid]['verdicts']['correct']['pass']} — {grades[arm][cid]['verdicts']['correct']['reason']}",'']
            report += ['<details><summary>선택된 근거 5개</summary>','','```json',json.dumps(sels[cid]['selected'],ensure_ascii=False,indent=2),'```','','</details>','']
    (OUT/'CASES.md').write_text('\n'.join(report)+'\n')
    print(json.dumps({'summary':summary,'paired_counts':{k:len(v) for k,v in pairs.items()},'verification':verify},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
