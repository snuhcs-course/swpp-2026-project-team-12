"""Report frozen original rubric scores and metered pilot costs, without relabeling."""
import hashlib
import statistics as st
import subprocess
from budget_lab import read, write, selection_metrics, candidates, MODES, digest
from run_pilot import ROOT, OUT, DATA, originals, rows, CONFIG

NAMES={'baseline':'기존 선택','interleave':'번갈아 선택','reranker':'Reranker'}


def main():
    bundle=read(OUT/'bundle.json')
    cases={c['id']:c for c in bundle['cases']}
    original={r['case']['id']:r for r in originals()}
    answers={(r['case_id'],r['mode']):r for r in rows(OUT/'answers.jsonl') if r['status']=='completed'}
    grades={(r['case_id'],r['mode']):r for r in rows(OUT/'grades.jsonl')}
    selections={(r['case_id'],r['mode']):r for r in read(OUT/'selection_comparison.json')['rows']}
    retrieval=read(OUT/'retrieval.json')
    embeddings=rows(OUT/'embedding_calls.jsonl')
    post_keys={f'post_{v}':k for k,v in read(DATA/'database_state.json')['post_ids'].items()}
    assert len(answers)==len(grades)==len(selections)==60
    assert digest([r['case'] for r in read(OUT/'original_cases.json')])==digest([r['case'] for r in originals()])
    detail=[]
    for cid in cases:
        for mode in MODES:
            a,g,s=answers[cid,mode],grades[cid,mode],selections[cid,mode]
            rank=s['reranker_call'] or {}
            rank_usage=rank.get('usage') or {}
            embed_tokens=sum(e['usage']['total_tokens'] for e in embeddings if e['case_id']==cid)
            verdict=g['verdicts']
            detail.append({'case_id':cid,'mode':mode,'correct':verdict['correct']['pass'],
                'answers_question':verdict['answers_question']['pass'],
                'no_stale_or_invented':verdict['no_stale_or_invented']['pass'],
                'all_judge_pass':all(v['pass'] for v in verdict.values()),
                **s['metrics'],
                'raw_required_recall':selection_metrics(cases[cid],candidates(cases[cid]))['required_recall'],
                'answer_input_tokens':a['usage']['input_tokens'],
                'answer_cached_input_tokens':a['usage'].get('input_tokens_details',{}).get('cached_tokens',0),
                'answer_output_tokens':a['usage']['output_tokens'],
                'answer_reasoning_tokens':a['usage'].get('output_tokens_details',{}).get('reasoning_tokens',0),
                'answer_total_tokens':a['usage']['total_tokens'],
                'rank_input_tokens':rank_usage.get('input_tokens',0),
                'rank_output_tokens':rank_usage.get('output_tokens',0),
                'rank_total_tokens':rank_usage.get('total_tokens',0),
                'llm_total_tokens':a['usage']['total_tokens']+rank_usage.get('total_tokens',0),
                'embedding_tokens':embed_tokens,
                'answer_seconds':a['answer_seconds'],'search_seconds':retrieval[cid]['seconds'],
                'rank_seconds':rank.get('seconds',0),
                'composed_seconds':retrieval[cid]['seconds']+rank.get('seconds',0)+a['answer_seconds'],
                'selected_ids':s['selected_ids'], 'answer':a['text'], 'verdicts':verdict})
    summary={}
    for mode in MODES:
        d=[x for x in detail if x['mode']==mode]
        summary[mode]={'n':len(d)}
        for k in ('correct','answers_question','no_stale_or_invented','all_judge_pass','required_all_present'):
            summary[mode][k+'_count']=sum(x[k] for x in d)
        for k in ('required_recall','raw_required_recall','source_count','context_utf8_bytes',
                  'answer_input_tokens','answer_cached_input_tokens','answer_output_tokens','answer_reasoning_tokens',
                  'answer_total_tokens','rank_input_tokens','rank_output_tokens','rank_total_tokens','llm_total_tokens',
                  'embedding_tokens','answer_seconds','search_seconds','rank_seconds','composed_seconds'):
            summary[mode][k+'_mean']=st.mean(x[k] for x in d)
        summary[mode]['answer_seconds_median']=st.median(x['answer_seconds'] for x in d)
    from portable import verify_code
    shared={'packaged_experiment_sources':verify_code()}
    verify={'shared_tracked_diff_unchanged':shared,'gold_cases_unchanged':True,'answers':60,'grades':60,
        'query_policy':'Original queries reused. No query-decision call was rerun.',
        'time_policy':'Composed search + reranker + answer, excludes query decision and grading; shared search measured once per case.',
        'request_policy':'Reconstructed self-contained requests, not original capture. Shared evaluation report timestamp.',
        'tokens_policy':'LLM input+output tokens; embeddings and grading separate. Not dollar costs.',
        'original_case_sha256':digest([r['case'] for r in originals()]),
        'source_hashes_match':{name:hashlib.sha256((ROOT/'frozen'/name).read_bytes()).hexdigest()==rec['sha256']
            for name,rec in read(ROOT/'source_lock.json').items()},
        'judge_calls':len(rows(OUT/'judge_calls.jsonl')),'embedding_calls':len(embeddings),
        'rank_calls':len(rows(OUT/'ranks.json.attempts.jsonl')),
        'answer_errors':rows(OUT/'answer_errors.jsonl'),
        'judge_errors':rows(OUT/'judge_errors.jsonl'),
        'actual_reported_tokens':{
            'answers':sum(a['usage']['total_tokens'] for a in answers.values()),
            'ranking':sum(r['call']['usage']['total_tokens'] for r in rows(OUT/'ranks.json.attempts.jsonl')),
            'embeddings':sum(e['usage']['total_tokens'] for e in embeddings),
            'grading':sum(r['usage']['total_tokens'] for r in rows(OUT/'judge_calls.jsonl'))}}
    assert all(verify['source_hashes_match'].values())
    write(OUT/'verification.json',verify)
    write(OUT/'results.json',{'summary':summary,'cases':detail,'verification':verify})
    lines=['# Post QA 선택 방식 예비 비교 — 2026-11-05','',
        '기존 평가셋의 20개 probe를 질문자 지민(`week_jimin`) 기준으로 1회씩 실행했다. 기존 선택·번갈아 선택·reranker 각 20건, 총 60건이다. 질문·정답·required/optional 라벨·채점 지시와 합격 기준은 수정하지 않았다.','',
        '## 조건','',
        '- 팀원 제공 그래프: 과거 게시글 80개 + 가족 registry 1개. 게시글 임베딩 1,024차원. 평가 글 20개는 기억에 적재하지 않았다.',
        '- 앱 복사본: `a6b8b96cdf52b200a96496d3b6ffa2810039eb10`; 채점 복사본: `da8f0ace179cef7ec7531914db0c8157392972fd`.',
        '- 동일한 기존 검색어로 후보를 한 번 조회하고, 세 방식에 같은 후보를 제공했다. 선택 상한은 총 5개다.',
        '- 번갈아 선택은 fact/episode 교차 후 같은 출처를 우선 중복 제거한다. 서로 다른 사실은 버리지 않고 빈자리가 있으면 다시 채운다.',
        '- Reranker는 Luna Fast로 후보 전체의 순위를 정해 상위 5개를 선택한다. 정답·라벨·참고 답안은 전달하지 않았다.',
        '- 답변: gpt-6-luna, reasoning none, service tier fast, 최대 출력 700. Reranker 최대 출력 4,096.',
        '- 채점: 기존 Luna judge 그대로 사용했다. reasoning과 service tier는 미지정, 최대 출력 2,000. 사진과 정답 참고 자료를 기존 방식대로 제공했다.',
        '- 최종 요청 원본이 없어서 앱 프롬프트·사진·본문·기존 검색어로 새 요청을 구성했다. 공통 현재시각은 원래 평가 보고서의 시각으로 고정했다. 과거 실행의 정확한 재현이나 전체 앱 속도 측정으로 해석하지 않는다.','',
        '## 결과','',
        '| 지표 | 기존 선택 | 번갈아 선택 | Reranker |','|---|---:|---:|---:|']
    def table(label,key,fmt):
        lines.append('| '+label+' | '+' | '.join(fmt(summary[m][key]) for m in MODES)+' |')
    table('정확도 (`correct`)','correct_count',lambda x:f'{x}/20 ({x*5:.0f}%)')
    table('질문에 직접 답함','answers_question_count',lambda x:f'{x}/20')
    table('옛 정보·허구 없음','no_stale_or_invented_count',lambda x:f'{x}/20')
    table('Required 근거 확보율 (평균 recall)','required_recall_mean',lambda x:f'{x:.1%}')
    table('Required 근거를 모두 확보한 질문','required_all_present_count',lambda x:f'{x}/20')
    table('채점 모든 항목 통과 (검색어 포함)','all_judge_pass_count',lambda x:f'{x}/20')
    table('답변 입력 토큰/질문','answer_input_tokens_mean',lambda x:f'{x:,.1f}')
    table('답변 출력 토큰/질문','answer_output_tokens_mean',lambda x:f'{x:,.1f}')
    table('답변 입력 중 캐시 토큰/질문','answer_cached_input_tokens_mean',lambda x:f'{x:,.1f}')
    table('재정렬 포함 LLM 토큰/질문','llm_total_tokens_mean',lambda x:f'{x:,.1f}')
    table('답변 호출 평균 시간','answer_seconds_mean',lambda x:f'{x:.2f}s')
    table('검색+재정렬+답변 합산 평균 시간','composed_seconds_mean',lambda x:f'{x:.2f}s')
    lines+=['','근거 확보율은 기존 required 라벨의 출처 게시글이 선택 결과에 포함됐는지 측정한다. 원문이 포함돼도 사실이 왜곡되어 있거나, optional에 질문의 필수 내용이 들어 있다면 답변 정확도와 다를 수 있다. 이번에는 이 기준을 보정하지 않았다.','',
        '토큰은 입력+출력이며 금액이 아니다. 재정렬 포함 LLM 토큰에는 답변과 reranker만 포함한다. 검색 임베딩은 아래에 별도로 기록했다. 실제 과금액은 모델·캐시·service tier에 따라 달라진다.',
        f"검색 임베딩은 실제 {len(embeddings)}회, {sum(e['usage']['total_tokens'] for e in embeddings):,}토큰이었다. 이 공통 검색 결과를 세 방식이 재사용했다.",
        '시간은 스트리밍 첫 응답이 아닌 호출 완료까지이며 첫 호출을 임의로 제외하지 않았다. 검색은 질문별 한 번 측정한 공통값을 사용한 합산 시간이다. 검색 판단·기억 구축·채점 시간은 제외했다. 응답 순서는 고정 seed로 섞었다.','',
        f"답변 생성 중 API 연결 실패 {len(rows(OUT/'answer_errors.jsonl'))}건, 채점 중 연결 실패 {len(rows(OUT/'judge_errors.jsonl'))}건을 별도 기록하고 해당 미완료 요청만 재개했다. 표는 완료된 호출 시간이며 실패 대기·수동 재개 시간은 포함하지 않는다. 응답을 받지 못한 호출의 사용량은 알 수 없어 0으로 단정하지 않는다.",'',
        '마지막 두 답변을 재개할 때 먼저 완료된 답변의 채점이 진행 중이었다. 따라서 이 예비 실행의 시간은 엄밀한 단독 부하 벤치마크가 아니다. 채점 자체의 시간·토큰은 답변 성능에 합산하지 않았다.','',
        '## 기존 합격 기준 적용','',
        '| 기준 | 기존 목표 | 기존 선택 | 번갈아 선택 | Reranker |','|---|---:|---:|---:|---:|']
    for label,key,target,den in [('정확도','correct_count',.8,20),('Required recall','required_recall_mean',.85,1),('옛 정보·허구 없음','no_stale_or_invented_count',.85,20)]:
        lines.append('| '+label+f' | ≥{target:.0%} | '+' | '.join('통과' if summary[m][key]/den>=target else '미달' for m in MODES)+' |')
    lines+=['','검색 판단 통과율은 검색어를 고정했으므로 이번 실험에서 새로 평가하지 않았다. 예비 20건·1회 반복이므로 전체 100건이나 반복 실행으로 일반화하지 않는다.','',
        '## 질문별 결과','', '| 질문 ID | 기존 정답 | 교차 정답 | Reranker 정답 | 근거 recall (기존/교차/재정렬) |', '|---|---:|---:|---:|---|']
    for cid in cases:
        vals=[next(x for x in detail if x['case_id']==cid and x['mode']==m) for m in MODES]
        lines.append('| '+cid.split('@')[0]+' | '+' | '.join('O' if x['correct'] else 'X' for x in vals)+' | '+' / '.join(f"{x['required_recall']:.0%}" for x in vals)+' |')
    lines+=['','## 기존 선택 대비','',
        '| 방식 | 새로 정답이 된 질문 | 기존 정답에서 실패로 바뀐 질문 | LLM 토큰 비율 | 합산 시간 비율 |',
        '|---|---:|---:|---:|---:|']
    for mode in ('interleave','reranker'):
        gained=sum(not grades[cid,'baseline']['verdicts']['correct']['pass'] and grades[cid,mode]['verdicts']['correct']['pass'] for cid in cases)
        lost=sum(grades[cid,'baseline']['verdicts']['correct']['pass'] and not grades[cid,mode]['verdicts']['correct']['pass'] for cid in cases)
        lines.append(f"| {NAMES[mode]} | {gained} | {lost} | {summary[mode]['llm_total_tokens_mean']/summary['baseline']['llm_total_tokens_mean']:.2f}× | {summary[mode]['composed_seconds_mean']/summary['baseline']['composed_seconds_mean']:.2f}× |")
    lines+=['','## 해석과 대표 실패','',
        '- 기존 선택은 20개 질문 모두 fact 5개로 예산을 채웠다. 검색에 잡힌 episode가 최종 입력에서 빠지는 문제가 실제로 재현됐다.',
        '- 번갈아 선택은 전시 장소·방울토마토 위치·니트 주인·산책 코스·공연 장소 등을 개선했다. 그러나 여행 질문에서는 목적지 근거가 빠져 기존 정답이 실패로 바뀌었다. 형식의 균형만으로 관련도가 보장되지는 않는다.',
        '- Reranker는 10개 질문을 추가로 맞혔지만 책 질문은 기존 정답에서 실패로 바뀌었다. 정확도 개선이 가장 컸으나 모든 기존 합격 기준을 충족한 것은 아니다.',
        '- 가족사진 스캔 질문은 번갈아 선택에서도 최신 `album-update` 원문이 전달됐지만 옛 담당자 선희라고 답했다. Reranker는 준호라고 맞혔다. 필요한 출처를 포함하는 것과 최신 사실을 올바르게 해석하는 것은 별개다.','',
        '| Reranker 실패 | 실제 결과 | 확인된 원인·한계 |','|---|---|---|',
        '| 바질 모종 (`basil-probe`) | 누가 줬는지 모른다고 답함 | `basil-gift` / `post_21`은 DB에 있지만 후보에 없음. 기존 검색어도 이름의 유래만 물음. 재정렬로 복원 불가. |',
        '| 도시락 (`lunchbox-probe`) | 김밥에서 무엇으로 바뀌었는지 모른다고 답함 | `lunchbox-change` / `post_25`는 DB에 있지만 후보에 없음. 재료 구입 기록 `post_65`가 같은 required 라벨을 충족해 recall은 100%지만 메뉴 변경의 직접 근거가 아님. |',
        '| 책 (`book-probe`) | 수진이 지금 읽고 있다고 답함 | 기록은 주말에 읽겠다는 계획. 기존 채점은 현재 행동으로 단정한 점을 실패로 판정. |',
        '| 금붕어 (`aquarium-probe`) | 오늘 준호가 담당한다고 답함 | 기록의 핵심은 준호가 늦는 날 지민이 대신한다는 조건. 기존 채점은 오늘 담당자를 확정한 점을 실패로 판정. |','',
        '바질 답변 1건에는 한국어 답변 앞에 영문 처리 설명이 섞였다. 원문을 그대로 보관했으며 새로운 감점 항목을 추가하지 않았다.','',
        '**잠정 판단:** 번갈아 선택은 호출을 추가하지 않는 개선 후보이고, reranker는 더 높은 정확도와 추가 비용·지연의 교환이다. 다음 검증에서는 누락된 직접 근거가 후보에 들어오는지와 조건·시점을 답변에서 보존하는지를 나눠 살펴볼 필요가 있다. 이번 실행에서는 검색어·평가 기준·공유 앱을 수정하지 않았다.','',
        '실제 답변·정답 원문·선택된 근거 게시글·채점 이유는 [FAILURES.md](FAILURES.md), 전체 수치는 [results.json](results.json)에 있다. 공유 앱의 tracked diff는 실행 전후 동일함을 확인했다.']
    (OUT/'RESULTS.md').write_text('\n'.join(lines)+'\n')
    failures=['# 실패 사례 — 기존 평가 기준 유지','',
        '한 방식이라도 correct=false인 질문을 모두 수록했다. 근거 누락과 답변 생성 실패를 구분하되, ambiguous/optional 기준을 바꾸거나 재채점하지 않았다.','']
    for cid in cases:
        if all(grades[cid,m]['verdicts']['correct']['pass'] for m in MODES):continue
        c=original[cid]['case']
        failures += [f"## {cid}",'',f"게시글: {c['caption']}",f"질문: {c['question']}",
            f"필수 라벨: {', '.join(c['required_memories'])}",f"Optional 라벨: {', '.join(c['optional_memories'])}",'','기존 정답 참고 기록:']
        failures += [f"- `{r['feed_key']}` ({r['created_at']}): {r['caption']}" for r in c['reference']]
        failures+=['']
        for mode in MODES:
            s=selections[cid,mode];g=grades[cid,mode]['verdicts'];a=answers[cid,mode]
            sources={x['id']:x for m in s['selected'] for x in m['sources']}
            failures += [f"### {NAMES[mode]} — {'정답' if g['correct']['pass'] else '실패'}",'',a['text'],'',
                f"채점 이유: {g['correct']['reason']}",
                f"Required recall: {s['metrics']['required_recall']:.0%}",'선택된 출처:']
            failures += [f"- `{post_keys.get(x['name'],x['name'])}` / `{x['name']}` / `{x['id']}`: {x['text']}" for x in sources.values()]
            failures+=['']
    (OUT/'FAILURES.md').write_text('\n'.join(failures)+'\n')
    print(json_summary(summary))


def json_summary(summary):
    import json
    return json.dumps(summary,ensure_ascii=False,indent=2)


if __name__=='__main__':main()
