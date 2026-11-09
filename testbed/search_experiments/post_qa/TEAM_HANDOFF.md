# 팀원에게 받을 자료

> 2026-11-05 수령 업데이트: 사진·media·SQLite·manifest·database_state·pipeline_state·기능별 결과·queries·judge cache·Neo4j export를 받았다. 아래는 원래 요청 목록이다. 현재 미확인인 자료는 **budget 전 원문 후보, 실제 final request, 실행 commit·최종 설정**이다. 이미 받은 파일을 다시 요청할 필요는 없다. `TEAM_RESULTS_REVIEW.md` 참조.

## 우선 요청할 최소 묶음

| 파일 | 필요한 이유 |
|---|---|
| 실제 실행 commit SHA, 수정된 코드가 있으면 diff, 민감정보를 뺀 모델 설정과 패키지 버전 | Notion의 commit placeholder를 실제 실행 버전으로 확정 |
| `feature_eval/post_qa.json` | 100케이스의 입력·생성 검색어·기존 답변·선택된 기억·채점 |
| `feature_eval/queries.json` | 97.5%와 64% 분석 결과 확인. **이 파일만으로 원문 후보를 복원할 수는 없음** |
| `raw_queries.json` (새 export가 필요할 수 있음) | `{검색어: search_many가 반환한 memories 전체}`. select_budget 이전 순서, ID, fact, sources.text, sources.name, recorded_at, valid_at, invalid_at, source_episode_ids 보존 |
| `final_requests.json` (새 capture가 필요할 수 있음) | `{case_id: 최종 client.responses.create 요청 kwargs}`. instructions, 원래 input/사진/대화, function_call과 call_id, tool_choice 등. 키·헤더·클라이언트 생성 인수 제외 |
| `manifest.json`, `database_state.json`, 별도 `gold.json`이 있다면 포함 | source의 `post_<ID>`를 게시글·정답 label에 정확히 대응 |

이 묶음이 충분하면 선택 실험과 최종 답변 replay를 위해 Neo4j를 새로 construction할 필요가 없다.
`post_qa.json`에 남는 memories는 이미 budget 적용 후라 전체 검색 후보의 대체물이 아니다.
최종 요청의 이미지는 앱이 전송한 data URL이면 그대로 보관한다. 사진이 포함되므로 공개 Git에 올리지 않는다.

## 전체 재현용 추가 자료

- `pipeline_state.json`, `test.sqlite3`, `media/`, 다운로드한 원본 사진 폴더.
- 같은 실행 시점 Neo4j dump 또는 노드·관계·임베딩 속성을 보존한 export와 복구 절차.
- Neo4j 버전, Graphiti 버전, 가족 `group_id`, embedding 모델·차원, construction 프롬프트와 모델 설정.
- 앱/질문/검색 모델과 service tier, reasoning effort, token limit, 실행 시간대.
- 사진·manifest·DB·그래프 파일 해시. 재생성 대신 원래 파일을 우선 전달.
- `.env`, OpenAI API 키, DB 비밀번호는 전달 파일에서 제외. 필요한 비밀 설정은 각자 로컬에서 설정.

## 기존 파일이 없을 때

1. 실행 결과가 남아 있다면 우선 그 자료부터 전달한다. 다시 전체 실험을 돌릴 필요는 없다.
2. `queries.json`에는 주로 검색 순위/label 분석만 있으므로 원문 후보가 없으면 기존 그래프에서 검색만 재실행해야 한다. 이 경우 embedding API 비용이 발생할 수 있고 원래 검색 결과와 완전히 같다는 보장은 없다. 이번 단계에서는 실행하지 않는다.
3. `final_requests.json`이 없으면 모델에 실제 전달했던 사진·대화·tool call 상태를 완전히 복원했다고 주장하지 않는다. 승인 후 별도 baseline capture 실행을 하거나, 요청을 재구성한 별도 실험으로 명시한다.

## 승인 후 캡처 방법

`capture_hook.capture_case(case_id, output_dir)`를 기존 평가기의 **case 한 개 실행 바깥**에 적용하면, 결과를 바꾸지 않고 budget 전 후보와 최종 요청을 기록한다. 이 hook 자체는 API를 호출하지 않지만 감싼 앱 실행에는 원래 비용이 발생한다. 이번에는 실행하지 않는다.

```python
# 별도 실험 프로세스, 순차 실행. 운영 서버/병렬 실행에 사용하지 않는다.
from capture_hook import capture_case
with capture_case(case['id'], 'captures'):
    result = existing_run_post_qa(case, ...)
```

파일명은 case ID의 hash, 내부에 `case_id`, `results`, `final_request`가 있다.
각 파일을 모아 `final_requests.json`을 case ID별로 만들고, `results`를 검색어별 `raw_queries.json`으로 만든다. 같은 검색어의 후보가 서로 다르면 하나로 덮어쓰지 말고 실행 시점별로 따로 보관한다.
이후 `import_team_bundle.py`로 검증한다. 미래 출처, 누락된 tool call, 서로 다른 내용을 가진 같은 memory ID 등은 오류로 중단한다.

## 보내기 전에 확인할 것

- [ ] 20개 probe × 5명 = 100케이스가 맞는가?
- [ ] candidate 순서와 원문을 줄이거나 요약하지 않았는가?
- [ ] 그래프·DB·ID 매핑·사진이 같은 실행분인가?
- [ ] 각 case의 질문 시각이 캡처되어 있는가?
- [ ] 원래 질문 이후 정보를 사용한 과거 시점 평가가 아닌가?
- [ ] 앱 commit과 실험 코드 commit을 둘 다 기록했는가?
- [ ] 유효한 API 키·DB 비밀번호를 제외했는가?

## 팀원에게 보낼 짧은 요청 문안

Post QA의 기존 선택 / fact·episode 번갈아 선택 / reranker를 같은 검색 결과로 비교하려고 합니다.
기존 `post_qa.json`, `queries.json`, `manifest.json`, `database_state.json`과 실제 실행 commit·모델 설정을 부탁드립니다.
가능하면 select_budget 전 전체 검색 결과(원문·ID·시간 포함)와 답변 모델의 최종 요청도 필요합니다.
이 둘을 저장하지 않았다면 우선 기존 결과만 공유해 주세요. 재실행은 비용 확인 후 별도로 진행하겠습니다.
전체 재현을 위해서는 같은 실행분의 사진/media, SQLite DB, Neo4j 스냅샷도 부탁드립니다. API 키와 비밀번호는 제외해 주세요.
