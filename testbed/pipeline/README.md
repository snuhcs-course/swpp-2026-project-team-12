# 평가 준비 Pipeline

데이터셋의 test DB를 만들고 Graphiti 기억을 구성합니다. 평가는 이 준비가 끝난 뒤 [feature_eval](../feature_eval/README.md)이 실행합니다.

```text
build → seed-memory → construct → seed-probes
```

| phase | 하는 일 | 비용 |
|---|---|---|
| `build` | `datasets/<이름>`으로 manifest와 사진을 만듭니다. | 없음 (사진이 저장소에 없으면 Pexels 다운로드) |
| `seed-memory` | probe를 뺀 게시물을 test DB에 넣습니다. | 없음 |
| `construct` | backend의 `run_construction_worker --once`로 게시물 설명을 만들고 Graphiti에 저장합니다. | OpenAI 유료 호출, Neo4j 필요 |
| `seed-probes` | 마지막 날 probe 게시물을 넣습니다. 기억에 들어가지 않은 상태로 질문을 받게 하려고 construct 뒤에 넣습니다. | 없음 |

```powershell
python -m testbed.pipeline --dataset family-week-100-five-members --phase all
# 한 단계씩, 또는 연속된 일부만
python -m testbed.pipeline --dataset family-week-100-five-members --phase build --phase seed-memory
```

- 이전 phase가 끝나지 않았으면 다음 phase를 중단합니다. 외부에서 같은 작업을 이미 마쳤을 때만 `--force`로 이 검사를 건너뜁니다.
- `build`를 다시 실행하면 완료 기록이 초기화됩니다. 이미 construct한 데이터셋은 build를 다시 하지 마세요.
- `--skip-images`는 사건 계획만 확인할 때 씁니다. 이 상태에서는 DB seed가 차단됩니다.
- 다른 TalkDock checkout을 대상으로 하려면 `--backend C:\path\to\backend`를 넘깁니다.

## 저장되는 상태

```text
testbed/output/<dataset_name>/pipeline_state.json   완료한 phase
testbed/output/<dataset_name>/database_state.json   가족방 ID와 feed_key → 게시물 ID
testbed/output/<dataset_name>/test.sqlite3, media/  평가용 test DB
```

test DB의 가족방 ID는 데이터셋마다 다르게 고정됩니다([가족방 ID와 Graphiti](../README.md#가족방-id와-graphiti)). 이미 다른 ID로 seed한 test DB에 다시 seed하면 오류가 납니다. 이때는 `test.sqlite3`, `media/`, `database_state.json`을 지우고 `seed-memory`부터 다시 실행합니다.

## 정답 추적

Graphiti 검색 결과의 source 이름은 `post_<게시물 ID>`입니다. `database_state.json`의 `post_ids`로 source를 `feed_key`로 되돌리고, 그 게시물의 `establishes` label을 probe 정답(`required_memories`, `must_filter`)과 비교합니다. 이 매핑은 `common/labels.py`에 있고 feature_eval의 post QA와 가족 기록 채점이 사용합니다.

## 알려진 제약

- `family-week-100-five-members`, `family-week-50-five-members`의 기존 test DB(2026-10-23)는 backend migration이 다시 작성되기 전 schema라 현재 backend로 열 수 없습니다. 이 데이터셋은 `test.sqlite3`, `media/`, `database_state.json`을 지우고 `seed-memory`부터 다시 실행해야 합니다(`construct` 유료).
