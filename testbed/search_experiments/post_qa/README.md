# Post QA selection and prompt experiments

공유 앱을 수정하지 않고 고정된 검색 후보와 최종 요청을 비교한다. `frozen/`, `candidate_selectors/`는 커밋별 참고·실행용 복사본이며 앱에 덮어쓰지 않는다.

- `budget_lab.py`: 기존 선택, 번갈아 선택, reranker.
- `run_pilot.py`, `run_full_once.py`: 처음 수행한 60건 예비/300건 1회 비교.
- `run_qa_prompt_compare.py`: interleave 고정, QA 지시문만 변경.
- `run_separate_budget.py`: `855cd61`의 fact 5 + episode 5 선택기.
- `frozen/judge_reference.py`: 당시 채점 기준. `source_lock.json`에 원본 hash와 커밋.
- `recorded.json.xz`: 원본 답변·채점·검색 후보 기록.
- `expected_metrics.json`: 오프라인 검증용 기존 집계 기준값.

## API 없는 검사

```sh
cd testbed/search_experiments/post_qa
python -m unittest discover -s tests -v
```

상위 README대로 별도 `post_qa-inputs.tar.gz`를 가져온 뒤에는:

```sh
python run_separate_budget.py prepare
python run_qa_prompt_compare.py prepare
```

각각 기존 200개/100개 요청 해시를 확인한다. 전자는 근거만, 후자는 instructions만 바뀌는지 검사한다. Neo4j/API 호출이 없다. `verify.py`는 이 자료 없이도 Git에 포함된 사진 없는 기록으로 세 선택 결과와 집계를 검증한다.

## 유료 재실행

환경변수 `OPENAI_API_KEY`를 사용한다. 사진이 포함된 요청을 OpenAI API로 전송한다. `--allow-paid`가 없으면 실행하지 않는다. 가져온 `outputs/`는 완료된 과거 결과이므로 기본 명령은 재호출하지 않는다. 새 비교는 **비어 있는 새 출력 폴더**로 분리한다.

```sh
export SEARCH_EXPERIMENT_OUTPUT="$PWD/outputs/separate_5_5_new_run"
python run_separate_budget.py prepare
python run_separate_budget.py run --allow-paid
python report_separate_budget.py
```

QA 지시문 비교는 새 출력 폴더를 지정한 후 `run_qa_prompt_compare.py run --allow-paid`와 `report_qa_prompt_compare.py`를 사용한다. 원래 A/B 답변은 고정하여 재사용하고 해당 후보의 100개 답변을 새로 생성한다. 동일 채점 재료는 캐시가 재사용될 수 있다.

이 패키지는 **고정 후보 replay**를 우선 지원한다. 검색부터 새로 실행하려면 팀원의 원본 그래프를 전용 Neo4j에 복원하고 `NEO4J_URI/USER/PASSWORD`를 지정해야 한다. MemoryQA 그래프를 연결하면 안 된다. `run_pilot.py retrieve`는 그 별도 환경과 임베딩 호출을 요구하며, 이번 PR 준비에서는 실행하지 않았다.

100건은 20주제 × 5열람자다. initial reranker 비교에는 API가 거절한 1건이 미채점으로 남아 있다. 5+5 비교의 A/B/C는 각 100건 채점 완료다. 요구 근거 라벨 확보율과 의미적 충분성을 구분하며, 지연은 최종 답변 호출/합산 추정치로 구분한다. 기존 판정의 관계·시간 누락 문제와 한계는 [공통 README](../README.md)의 채점 주의사항을 참고한다.
