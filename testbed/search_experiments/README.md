# Search experiments — Iteration 3

실험 결과 검증과 재실행용 패키지다. 앱 코드는 변경하지 않는다. 숫자를 다시 계산하는 데에는 API·Neo4j·사진이 필요 없다.

| 실험 | 평가 데이터 / 반복 | 비교 |
|---|---|---|
| Post QA selection | 팀원 제공 5인 가족, 20개 주제 × 열람자 5명, 1회 | 기존 합계 5개 / 번갈아 5개 / reranker 5개 / fact 5 + episode 5 |
| Post QA prompt | 같은 100건, 1회 | 번갈아 선택 고정, 기존 / 수정 QA 지시문 |
| Family History Search | MemoryQA 사진 기반 합성 4인 가족, 100/200/300개 과거 글, 공통 30문항 × 3회 | Full History / Graphiti, 총 540건 |

Post QA의 100건은 독립적인 100개 주제가 아니다. 가족 추억 찾기의 30문항과도 다른 평가셋이다. MemoryQA 원본 정답을 그대로 평가한 실험은 아니다.

## 결과 확인 — API 없이

저장소 루트에서 Python 3.12를 권장한다.

```sh
python3 -B testbed/search_experiments/verify.py
cd testbed/search_experiments/post_qa
python3 -B -m unittest discover -s tests -v
```

`verify.py`는 저장된 답변·원시 채점·usage·시간에서 결과를 재계산하고, 세 선택 알고리즘을 실제 후보에 다시 적용한다. 유료 호출과 DB 접근은 없다. `verification.json`은 로컬 생성물이다.

`recorded.json.xz`에는 사진 없는 원본 답변·채점·근거·측정 기록이 있다. Post QA의 사진 포함 전체 요청은 별도 재실행 자료에만 있다. `post_qa/expected_metrics.json`은 기존 결과에서 추출한 검증 기준값이다. Family History는 원본 기록 안의 `full_metrics.json`과 비교한다.

전체 사례·실패 목록·중간 보고서는 Git에서 제외한다. 필요한 보고서는 각 실행 안내의 보고서 생성 명령으로 로컬에 만든다. [평가 문항](family_history/cases.json)과 원본 기록은 유지한다.

## 재실행 준비

실제 API 재호출은 이 PR의 오프라인 검증과 별개다. 아래 자료를 실험 담당자에게 받아야 한다. 현재 외부 공개 다운로드 주소는 없다.

| 별도 자료 | 크기(약) | 용도 |
|---|---:|---|
| `family_history-inputs.tar.gz` | 6.5 MiB | 기존 설명, SQL 복사본, 3개 규모 그래프·임베딩, 출처 매핑 |
| `post_qa-inputs.tar.gz` | 63.9 MiB | 팀원 원본 export·사진, 고정 후보/요청, 과거 답변·채점 캐시 |

파일별 SHA-256과 archive SHA-256은 `artifacts.json`에 있다. 사진, SQLite, Neo4j 스냅샷, 가상환경, 키는 Git에 포함하지 않는다. 자료를 가져오는 과정은 바이트 동일성을 검사하고 변경된 파일을 덮어쓰지 않는다.

```sh
python3 -m venv .venv-search
.venv-search/bin/pip install -r testbed/search_experiments/requirements-live.txt
.venv-search/bin/python testbed/search_experiments/setup_artifacts.py family_history /path/to/family_history-inputs.tar.gz
.venv-search/bin/python testbed/search_experiments/setup_artifacts.py post_qa /path/to/post_qa-inputs.tar.gz
```

모델 이름·service tier는 당시 설정을 유지한다. 실행 계정이 `gpt-6-luna` / `fast`를 지원하는지 확인해야 하며 다른 모델로 자동 대체하지 않는다. 새 환경의 의존성 설치와 유료 호출까지 검증했다는 의미는 아니다.

- [Family History 실행](family_history/README.md)
- [Post QA 실행](post_qa/README.md)
- [이번 패키지 검증](VALIDATION.md)

## 고정 조건과 해석

Family History는 앱 `ed296d4`, 이전 `2c24972`에서 생성한 그래프를 재사용했다. Post QA는 앱 `a6b8b96`, 평가 코드 `da8f0ac`, 5+5 선택기는 `855cd61`이다. 프롬프트·정답·채점 판정은 포장 과정에서 바꾸지 않았다.

`original_code_hashes.json`은 원래 실험 코드, 각 `portable_code_lock.json`은 이식된 실행 코드다. 이식 변경은 경로·명시적 환경변수·패키지 무결성 검사·보고서 저장 위치에 한정된다. 원래의 로컬 체크아웃 검사 대신 패키지 해시를 검사하며, 원래 실행 당시 기록은 `recorded.json.xz`와 `family_history/provenance/`에 보존한다.

토큰 수는 청구 비용이 아니다. Family History 시간은 검색+답변, Post QA 표의 답변 시간은 최종 호출이며 앱 전체 지연이 아니다. 두 실험의 시간을 직접 비교하지 않는다. Family History의 자동 Memory Update Error 판정은 수동 검수와 불일치해 해석을 보류한다. 평가 기준은 사후 변경하지 않았다.

## 채점 주의사항

- 점수는 기존 모델 채점이며 독립적인 사람 평가가 아니다. 평가셋과 원시 판정은 수정하지 않았다.
- Family History의 Memory Update Error에는 오래된 결제 상태를 답했는데도 오류가 아니라고 판정한 사례가 있다. 자동 집계 0%를 오류가 없다는 근거로 사용하지 않는다.
- Family History 채점기는 검색된 모든 미표시 기록을 보지 않아 부수적 허구 판정이 부정확할 수 있다. Post QA 채점 입력에도 답변 모델이 받은 관계·게시 시각이 빠진 사례가 있다. 이런 판정만으로 환각이나 프롬프트 개선을 단정하지 않는다.
- 시간 적용을 유보한 답변과 조건·관계 표현의 정오에는 경계 사례 및 채점 불일치가 있다. 정답 충족률과 근거 확보율을 별도로 읽는다. 근거 ID/라벨 확보는 의미적 충분성과 같지 않다.
- 규모별 그래프는 각각 구축됐으므로 규모 효과와 fact 추출 차이가 섞인다. 반복 호출은 독립 질문 수를 늘리지 않는다. 캐시·실행 시점 차이가 있어 지연 차이를 선택 방식이나 프롬프트만의 효과로 해석하지 않는다.
