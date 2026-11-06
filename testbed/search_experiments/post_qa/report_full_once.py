"""Report 100 cases x three selectors x one repeat, preserving all original labels."""
import hashlib
import statistics as st
import subprocess
from budget_lab import read, write, selection_metrics, candidates, MODES, digest, rank_key
from run_full_once import ROOT, OUT, CONFIG, ALL
from run_pilot import DATA, rows

def originals():
    return ALL

NAMES={'baseline':'기존 선택','interleave':'번갈아 선택','reranker':'Reranker'}


def main():
    bundle=read(OUT/'bundle.json')
    cases={c['id']:c for c in bundle['cases']}
    original={r['case']['id']:r for r in originals()}
    answers={(r['case_id'],r['mode']):r for r in rows(OUT/'answers.jsonl') if r['status']=='completed'}
    grades={(r['case_id'],r['mode']):r for r in rows(OUT/'grades.jsonl')}
    successful_count=len(answers)
    graded_count=len(grades)
    terminal={(r['case_id'],r['mode']):r for r in rows(OUT/'terminal_errors.jsonl')}
    for key,error in terminal.items():
        assert key not in answers and key not in grades
        # In-memory placeholders for table alignment only. No fabricated judge logs.
        answers[key]={'status':'api_rejected','text':f"답변 미생성: API {error['code']} (재시도하지 않음)",
            'usage':{'input_tokens':0,'output_tokens':0,'total_tokens':0},'answer_seconds':0}
        grades[key]={'status':'ungraded','verdicts':{k:{'pass':None,'reason':'API 거절로 답변이 없어 채점하지 않음'}
            for k in ('correct','answers_question','no_stale_or_invented','queries_fit')}}
    selections={(r['case_id'],r['mode']):r for r in read(OUT/'selection_comparison.json')['rows']}
    retrieval=read(OUT/'retrieval.json')
    embeddings=rows(OUT/'embedding_calls.jsonl')
    post_keys={f'post_{v}':k for k,v in read(DATA/'database_state.json')['post_ids'].items()}
    assert len(answers)==len(grades)==len(selections)==300
    assert digest([r['case'] for r in read(OUT/'original_cases.json')])==digest([r['case'] for r in originals()])
    rank_attempts=rows(OUT/'ranks.json.attempts.jsonl')
    detail=[]
    for cid in cases:
        for mode in MODES:
            a,g,s=answers[cid,mode],grades[cid,mode],selections[cid,mode]
            rank=s['reranker_call'] or {}
            rank_usage=rank.get('usage') or {}
            attempts=[r['call'] for r in rank_attempts if mode=='reranker' and r['key']==rank_key(cases[cid],CONFIG['reranker_options'])]
            attempt_tokens=sum(r['usage']['total_tokens'] for r in attempts)
            attempt_seconds=sum(r['seconds'] for r in attempts)
            embed_tokens=sum(e['usage']['total_tokens'] for e in embeddings if e['case_id']==cid)
            verdict=g['verdicts']
            detail.append({'case_id':cid,'mode':mode,'correct':verdict['correct']['pass'],
                'answers_question':verdict['answers_question']['pass'],
                'no_stale_or_invented':verdict['no_stale_or_invented']['pass'],
                'all_judge_pass':all(v['pass'] for v in verdict.values()) if (cid,mode) not in terminal else None,
                'evaluation_status':'api_rejected_ungraded' if (cid,mode) in terminal else 'graded',
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
                'llm_known_attempt_tokens':a['usage']['total_tokens']+attempt_tokens,
                'embedding_tokens':embed_tokens,
                'answer_seconds':a['answer_seconds'],'search_seconds':retrieval[cid]['seconds'],
                'rank_seconds':rank.get('seconds',0),
                'composed_seconds':retrieval[cid]['seconds']+rank.get('seconds',0)+a['answer_seconds'],
                'composed_rank_attempt_seconds':retrieval[cid]['seconds']+attempt_seconds+a['answer_seconds'],
                'selected_ids':s['selected_ids'], 'answer':a['text'], 'verdicts':verdict})
            if (cid,mode) in terminal:
                for field in ('answer_input_tokens','answer_cached_input_tokens','answer_output_tokens',
                    'answer_reasoning_tokens','answer_total_tokens','llm_total_tokens','llm_known_attempt_tokens',
                    'answer_seconds','composed_seconds','composed_rank_attempt_seconds'):
                    detail[-1][field]=None
    summary={}
    for mode in MODES:
        d=[x for x in detail if x['mode']==mode]
        summary[mode]={'n':len(d)}
        summary[mode]['graded_count']=sum(x['evaluation_status']=='graded' for x in d)
        summary[mode]['api_rejected_count']=sum(x['evaluation_status']!='graded' for x in d)
        for k in ('correct','answers_question','no_stale_or_invented','all_judge_pass','required_all_present'):
            summary[mode][k+'_count']=sum(x[k] is True for x in d)
        for k in ('required_recall','raw_required_recall','source_count','context_utf8_bytes',
                  'answer_input_tokens','answer_cached_input_tokens','answer_output_tokens','answer_reasoning_tokens',
                  'answer_total_tokens','rank_input_tokens','rank_output_tokens','rank_total_tokens','llm_total_tokens',
                  'embedding_tokens','answer_seconds','search_seconds','rank_seconds','composed_seconds',
                  'llm_known_attempt_tokens','composed_rank_attempt_seconds'):
            summary[mode][k+'_mean']=st.mean(x[k] for x in d if x[k] is not None)
        summary[mode]['answer_seconds_median']=st.median(x['answer_seconds'] for x in d if x['answer_seconds'] is not None)
    from portable import verify_code
    shared={'packaged_experiment_sources':verify_code()}
    verify={'shared_tracked_diff_unchanged':shared,'gold_cases_unchanged':True,'answers':successful_count,'grades':graded_count,
        'terminal_ungraded':list(terminal.values()),'scheduled_cases':300,
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
    pilot=ROOT/'outputs/pilot60'
    reuse=read(OUT/'pilot_reuse.json')
    for name,expected in reuse['copied_file_hashes'].items():
        assert hashlib.sha256((pilot/name).read_bytes()).hexdigest()==expected
    for name in ('answers.jsonl','grades.jsonl','judge_calls.jsonl','embedding_calls.jsonl'):
        assert (OUT/name).read_bytes().startswith((pilot/name).read_bytes()), 'Pilot logs changed'
    verify['pilot_preserved']=True
    verify['reused_answers']=60
    verify['new_answers']=successful_count-60
    verify['repeats']=1
    verify['unique_probes']=len({c['probe_id'] for c in cases.values()})
    verify['viewers']=len({r['case']['viewer_username'] for r in ALL})
    write(OUT/'verification.json',verify)
    grouped={}
    for group_key,func in [('viewer',lambda c:original[c]['case']['viewer_username']),
                           ('probe',lambda c:original[c]['case']['feed_key'])]:
        grouped[group_key]={}
        for label in dict.fromkeys(func(cid) for cid in cases):
            grouped[group_key][label]={}
            for mode in MODES:
                d=[x for x in detail if x['mode']==mode and func(x['case_id'])==label]
                grouped[group_key][label][mode]={'n':len(d),'correct':sum(x['correct'] is True for x in d),
                    'required_recall':st.mean(x['required_recall'] for x in d)}
    paired={}
    common=[cid for cid in cases if all((cid,m) not in terminal for m in MODES)]
    common_summary={m:{'n':len(common),'correct':sum(grades[cid,m]['verdicts']['correct']['pass'] is True for cid in common)} for m in MODES}
    for mode in ('interleave','reranker'):
        paired[mode]={}
        for name,oldpass,newpass in [('gained',False,True),('lost',True,False)]:
            paired[mode][name]=[cid for cid in cases if
                grades[cid,'baseline']['verdicts']['correct']['pass']==oldpass and
                grades[cid,mode]['verdicts']['correct']['pass']==newpass]
    write(OUT/'results.json',{'summary':summary,'common_graded_summary':common_summary,'by_group':grouped,'paired':paired,'cases':detail,'verification':verify})
    lines=['# Post QA 근거 선택 — 전체 100케이스, 방식별 1회','',
        f'**20문항 × 질문자 5명 × 3방식 × 1회 = 300케이스.** 예비 지민 60건을 보존하고 나머지 240케이스를 실행했다. 답변 생성·채점 {successful_count}건, API 거절로 미채점 {len(terminal)}건이다. 거절된 입력을 수정하거나 재요청하지 않았다.','',
        '## 고정한 조건','',
        '- 원본 평가셋의 질문·정답·required/optional·제외 근거·사진·관계·채점 지시·기존 합격 기준을 그대로 사용했다.',
        '- 기존 생성 검색어로 케이스별 후보를 한 번 확보하고 세 선택 방식에 동일하게 제공했다. 검색 판단 자체는 다시 실행하지 않았다.',
        '- 기존 선택 / fact와 episode를 번갈아 선택하고 출처 중복을 줄이는 방식 / Luna Fast reranker. 최종 선택 예산은 모두 5개다.',
        '- 팀원 제공 그래프를 별도 DB에 복원: 과거 게시글 episode 80개 + 가족 registry 1개, 총 105 nodes / 281 edges. 평가 글 20개는 기억에 넣지 않았다. 공유 앱·DB는 변경하지 않았다.',
        '- 답변·reranker: gpt-6-luna, reasoning none, service tier fast. 출력 상한 답변 700 / reranker 4,096.',
        '- 채점: 원본 Luna judge, reasoning/tier 미지정, 최대 출력 2,000. 별도 평가 보정이나 재채점으로 점수를 바꾸지 않았다.',
        '- 앱 프롬프트·검색 복사본 a6b8b96, 평가 복사본 da8f0ac. 과거 API 요청 원본이 없어 최종 요청은 재구성했다. 공통 현재시각은 원래 평가 보고서의 시각으로 고정했다.',
        '- 지민 60건은 최종 요청 hash·선택 근거·원본 case가 동일함을 확인해 재사용했다. 입력·출력 사용량과 지연은 캐시 재사용 시간을 0으로 넣지 않고 실제 측정값을 유지했다.','',
        '## 전체 결과','',
        '| 지표 | 기존 선택 | 번갈아 선택 | Reranker |','|---|---:|---:|---:|']
    def table(label,key,fmt):
        lines.append('| '+label+' | '+' | '.join(fmt(summary[m][key]) for m in MODES)+' |')
    table('채점된 답변 수','graded_count',lambda n:str(n))
    table('API 거절 (미채점)','api_rejected_count',lambda n:str(n))
    for label,key in [('정답/전체 케이스 (correct)','correct_count'),('질문에 직접 답함','answers_question_count'),
                      ('옛 정보·허구 없음','no_stale_or_invented_count'),('필수 근거 모두 확보','required_all_present_count'),
                      ('채점 모든 항목 통과 (검색어 포함)','all_judge_pass_count')]:
        table(label,key,lambda n:f'{n}/100 ({n}%)')
    table('Required 근거 확보율 (평균 recall)','required_recall_mean',lambda n:f'{n:.1%}')
    lines.append('| 채점된 답변의 정확도 | '+' | '.join(f"{summary[m]['correct_count']/summary[m]['graded_count']:.1%}" for m in MODES)+' |')
    lines.append('| 세 방식 모두 응답한 공통 케이스 정확도 | '+' | '.join(f"{common_summary[m]['correct']}/{len(common)} ({common_summary[m]['correct']/len(common):.1%})" for m in MODES)+' |')
    table('선택 전 후보의 Required recall','raw_required_recall_mean',lambda n:f'{n:.1%}')
    for label,key in [('답변 입력 토큰/케이스','answer_input_tokens_mean'),('답변 출력 토큰/케이스','answer_output_tokens_mean'),
                      ('답변 입력 중 캐시 토큰/케이스','answer_cached_input_tokens_mean'),
                      ('재정렬 입력+출력 토큰/케이스','rank_total_tokens_mean'),
                      ('답변+재정렬 LLM 토큰/케이스','llm_total_tokens_mean')]:
        table(label,key,lambda n:f'{n:,.1f}')
    table('실패 재정렬 응답 포함 LLM 토큰/케이스','llm_known_attempt_tokens_mean',lambda n:f'{n:,.1f}')
    for label,key in [('답변 평균 시간','answer_seconds_mean'),('답변 중앙값 시간','answer_seconds_median'),
                      ('재정렬 평균 시간','rank_seconds_mean'),('검색+재정렬+답변 합산 평균','composed_seconds_mean')]:
        table(label,key,lambda n:f'{n:.2f}s')
    table('실패 재정렬 응답 시간 포함 합산 평균','composed_rank_attempt_seconds_mean',lambda n:f'{n:.2f}s')
    lines+=['','근거 확보율은 기존 required 라벨의 출처 게시글이 선택됐는지를 뜻한다. 직접 답을 뒷받침하는 모든 내용이 확보됐다는 뜻은 아니다. 기존 라벨과 채점 기준을 바꾸지 않았다.',
        '토큰은 입력+출력 합계이며 금액이 아니다. 위 LLM 토큰은 답변+재정렬만 포함하며 검색 임베딩·채점은 분리했다.',
        f"검색 임베딩 성공 {verify['embedding_calls']}회, {verify['actual_reported_tokens']['embeddings']:,}토큰. 재정렬 {verify['rank_calls']}회, 답변 생성 {successful_count}회, 채점 API {verify['judge_calls']}회. 이 수에는 예비 실행에서 재사용한 기록도 포함된다.",
        '정답/전체 케이스는 정답 개수를 방식별 100케이스로 나눈 값이다. API 거절을 LLM의 채점 오답으로 위장하지 않고 미채점으로 따로 표시했다. 답변·합산 토큰/시간 평균은 응답을 받은 케이스만 대상으로 하며 미확인 사용량을 0으로 넣지 않았다. 재정렬 자체와 근거 지표는 모든 케이스를 포함한다.',
        '시간은 완료 응답까지이며 검색 판단·기억 구축·채점은 제외했다. 공통 검색을 케이스별 한 번 측정해 세 방식에 같은 값을 합산했다. 첫 요청을 임의로 제외하지 않았다. 답변은 순차 호출했으며 추가 240건의 채점은 답변 생성 완료 후 4개씩 병렬로 수행했다.',
        '표는 성공한 호출의 시간이다. API 오류와 재시도 대기는 별도 로그에 기록했다. 예비 마지막 두 답변은 채점과 중첩됐고 이번 결과에는 그 측정값도 그대로 포함했다. 예비와 추가 실행 시점이 다르므로 엄밀한 단일 세션 지연 비교는 아니다.',
        '재정렬 중 출력 한도에 도달한 응답은 원문·사용량을 보존하고 같은 설정으로 재요청했다. 정상 호출 표와 별도로 실패한 재정렬 응답의 토큰·시간을 포함한 행을 제시했다. 응답을 못 받은 네트워크 오류의 미확인 사용량은 0으로 단정하지 않는다.',
        '**이 결과는 선택 방식 비교이며 원래 앱 전체 경로의 정확한 재실행은 아니다.** 100케이스는 서로 독립적인 100문항이 아니라 같은 20문항의 질문자 5명 버전이다.','',
        '## 기존 선택 대비','',
        '| 방식 | 정답으로 개선 | 정답에서 실패로 변경 | LLM 토큰 비율 | 합산 시간 비율 |','|---|---:|---:|---:|---:|']
    for m in ('interleave','reranker'):
        lines.append(f"| {NAMES[m]} | {len(paired[m]['gained'])} | {len(paired[m]['lost'])} | {summary[m]['llm_total_tokens_mean']/summary['baseline']['llm_total_tokens_mean']:.2f}× | {summary[m]['composed_seconds_mean']/summary['baseline']['composed_seconds_mean']:.2f}× |")
    lines+=['','## 기존 합격 기준','',
        '| 지표 | 목표 | 기존 선택 | 번갈아 선택 | Reranker |','|---|---:|---:|---:|---:|']
    for label,key,target,den in [('정확도','correct_count',.8,100),('Required recall','required_recall_mean',.85,1),
                                ('옛 정보·허구 없음','no_stale_or_invented_count',.85,100)]:
        lines.append('| '+label+f' | ≥{target:.0%} | '+' | '.join('통과' if summary[m][key]/den>=target else '미달' for m in MODES)+' |')
    lines+=['','검색 판단 통과율은 검색어를 재사용했으므로 이번 실행에서 새로 평가하지 않았다.','',
        '## 질문자별 정확도','', '| 질문자 | 기존 선택 | 번갈아 선택 | Reranker |','|---|---:|---:|---:|']
    viewers={r['case']['viewer_username']:r['case']['viewer_name'] for r in ALL}
    for viewer,values in grouped['viewer'].items():
        lines.append('| '+viewers[viewer]+' | '+' | '.join(f"{values[m]['correct']}/20" for m in MODES)+' |')
    lines+=['','## 문항별 정확도','', '| 문항 | 기존 선택 | 번갈아 선택 | Reranker |','|---|---:|---:|---:|']
    for probe,values in grouped['probe'].items():
        lines.append('| '+probe+' | '+' | '.join(f"{values[m]['correct']}/5" for m in MODES)+' |')
    updates=('school-probe','tomato-probe','laundry-probe','exercise-probe','album-probe')
    update_counts={m:sum(grouped['probe'][p][m]['correct'] for p in updates) for m in MODES}
    lines+=['','## 해석과 대표 사례','',
        '- 기존 선택은 모든 100케이스에서 fact만으로 5개를 채웠다. episode가 검색에 잡혀도 답변 입력에서 밀려나는 현상이 재현됐다.',
        f"- 사전에 문제를 확인했던 전시 장소·화분 위치·니트 주인·산책 코스·사진 스캔 담당의 갱신 사례 25건은 기존 {update_counts['baseline']}/25 → 번갈아 선택 {update_counts['interleave']}/25 → reranker {update_counts['reranker']}/25였다.",
        f"- 번갈아 선택은 기존 오답 {len(paired['interleave']['gained'])}건을 개선했지만 기존 정답 {len(paired['interleave']['lost'])}건을 놓쳤다. 여행은 5/5 → 2/5, 목도리는 4/5 → 2/5였다. 원문에 기회를 주는 것만으로 질문에 필요한 여러 근거가 모두 보존되지는 않는다.",
        f"- Reranker는 기존 오답 {len(paired['reranker']['gained'])}건을 개선하고 기존 정답 {len(paired['reranker']['lost'])}건에서 실패했다. 선택 후 required recall은 선택 전 후보의 recall과 같았다. 라벨 기준으로는 후보 안의 필수 근거를 모두 유지했지만 답변 정확도가 그만큼 높아지는 것은 아니다.",
        '- 생일(도윤·선희 질문자)의 케이크 변경, 발표회(선희 질문자)의 장소 변경은 필요한 required 라벨이 선택 전 후보부터 없었다. 후보 밖의 정보를 reranker가 복원할 수는 없다.',
        '- 바질 모종 제공자 질문은 세 방식 모두 0/5였다. 기존 필수 라벨이 이름만 평가하므로 근거 recall은 100%여도 제공자 답변을 못 할 수 있다. 라벨을 수정하지 않았다.',
        '- 도시락은 재료 구입 기록과 메뉴 변경 기록을 구분해야 한다. 직접 변경 근거가 없는 후보에서는 reranker도 최종 메뉴를 확인하지 못했다.',
        '- 반려견 산책은 reranker에서도 도윤·수진·선희 질문자에게 옛 담당자 도윤으로 답했다. 현재 담당자 지민의 출처 라벨을 확보해도 옛 사실과 새 기록의 해석이 실패할 수 있다.',
        '- 금붕어는 reranker에서도 0/5였다. 기존 채점은 조건부 대리 급여 약속을 오늘의 확정 담당자로 말한 점을 실패로 판정했다. 시점·조건의 애매함에 대한 점수 보정은 하지 않았다.','',
        '## 채점 해석 시 유의할 사례 — 원점수 유지','',
        '채점기의 원래 입력은 작성자·본문·질문자·질문·정답 참고 기록이며, 답변 모델에 준 게시시각과 관계를 모두 포함하지 않는다. 다음 두 경우도 기존 판정 그대로 실패에 포함했다. 새로운 기준이나 보정 점수는 만들지 않았다.',
        '- `bicycle-probe@week_sujin` reranker: 답변의 “10월 18일에도”를 근거 없는 날짜라고 판정했다. 그러나 답변 모델 입력에는 게시시각 2026-10-18과 본문의 “오늘”이 있었다.',
        '- `movie-probe@week_junho` reranker: “도윤 외할아버지”를 근거 없는 호칭이라고 판정했다. 답변 모델에는 관계가 “외할아버지”로 주어졌다.',
        '이 두 사례를 순수한 답변 모델의 사실 오류라고 단정하면 안 된다. 이번 숫자는 원래 채점기로 얻은 비교 점수이며 인간 검수로 보정한 정확도는 아니다.','',
        '## 잠정 결론','',
        '번갈아 선택은 추가 LLM 호출 없이 개선되지만 일부 복합 질문에서는 기존 정답을 잃었다. Reranker는 근거 보존과 정확도 개선이 가장 컸으나 토큰·지연이 늘고 기존 정확도·옛 정보 방지 목표에는 아직 못 미쳤다. 다음 수정 대상은 후보 누락과 최신 사실·조건 해석을 분리해서 잡는 것이 적절하다. 공유 앱에는 반영하지 않았다.']
    lines+=['','실패 케이스의 질문·답변·정답·채점 이유·선택 근거는 [FAILURES.md](FAILURES.md), 전체 수치는 [results.json](results.json), 설정과 보존 검증은 [verification.json](verification.json)에 있다.']
    (OUT/'RESULTS.md').write_text('\n'.join(lines)+'\n')
    # Original evidence is kept once per failing case rather than hidden behind only scores.
    lines=['# 실패 사례 — 전체 100케이스, 방식별 1회','',
        '한 방식 이상 correct=false인 케이스를 수록했다. 기준을 보정하거나 점수를 수정하지 않았다.','']
    for cid in cases:
        if all(grades[cid,m]['verdicts']['correct']['pass'] for m in MODES):continue
        c=original[cid]['case']
        lines += [f'## {cid}','',f"작성자 {c['author_name']} / 질문자 {c['viewer_name']} / 관계 {c['expected_relationship']}",
            f"게시글: {c['caption']}",f"질문: {c['question']}",
            f"필수 라벨: {', '.join(c['required_memories'])}",f"Optional 라벨: {', '.join(c['optional_memories'])}",'','기존 정답 기록:']
        lines += [f"- `{r['feed_key']}` ({r['created_at']}): {r['caption']}" for r in c['reference']]
        lines+=['','기존 검색어:']+[f"- {r['query']}" for r in cases[cid]['results']]+['']
        for m in MODES:
            s=selections[cid,m];g=grades[cid,m]['verdicts'];a=answers[cid,m]
            src={x['id']:x for mem in s['selected'] for x in mem['sources']}
            label='미채점(API 거절)' if (cid,m) in terminal else ('정답' if g['correct']['pass'] else '실패')
            lines += [f"### {NAMES[m]} — {label}",'',a['text'],'',
                f"채점 이유: {g['correct']['reason']}",f"Required recall: {s['metrics']['required_recall']:.0%}",'선택 근거:']
            lines += [f"- `{post_keys.get(x['name'],x['name'])}` / `{x['name']}` / `{x['id']}`: {x['text']}" for x in src.values()]
            lines+=['']
    (OUT/'FAILURES.md').write_text('\n'.join(lines)+'\n')
    import json
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
