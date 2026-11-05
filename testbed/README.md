# TalkDock AI Testbed

TalkDock의 AI 기능을 고정된 가족 피드 데이터셋으로 평가하는 도구 모음입니다. 모든 명령은 저장소 루트에서 `python -m testbed.<모듈>` 형태로 실행합니다.

## 구성

```text
testbed/
  datasets/           데이터셋 정의 (config, 사건 catalog, 사진 출처, 사진 파일)
  builder/            데이터셋 build, 앱 DB에 넣기 (seed_app)
  pipeline/           평가 전 준비: test DB seed와 Graphiti 기억 구성
  feature_eval/       AI 기능 5개 평가 (규칙 기반 채점 + LLM judge; 가족 기록 검색은 memoryqa_scaling)
  common/             Django adapter, 실행 상태, 기억 label 매핑
  tests/              위 코드의 단위 테스트
  output/             실행 결과 (Git에 포함하지 않음)
  memoryqa_scaling/   과거 commit에 고정된 독립 MemoryQA 실험 (자체 README 참고)
```

| 무엇을 하고 싶은지 | 명령 | 문서 |
|---|---|---|
| 데이터셋을 만들거나 고치기 | `python -m testbed.builder --dataset <이름>` | [datasets/README.md](datasets/README.md) |
| 서버에서 데이터셋 가족 보기 | `python -m testbed.builder.seed_app --dataset <이름>` | [datasets/README.md](datasets/README.md#앱-db에-넣기) |
| 평가용 test DB와 Graphiti 기억 준비 | `python -m testbed.pipeline --dataset <이름> --phase all` | [pipeline/README.md](pipeline/README.md) |
| AI 기능 평가 | `python -m testbed.feature_eval --dataset <이름> --feature all` | [feature_eval/README.md](feature_eval/README.md) |

`--dataset`에는 `datasets/` 아래 폴더 이름, 데이터셋 폴더 경로, config 파일 경로 중 하나를 씁니다.

## 데이터셋

| 이름 | 가족 | 게시물 | 기능 평가용 문항 |
|---|---|---|---|
| `example` | 4명 | 20개 | probe 질문 4개 |
| `family-week-100-five-members` | 5명 (지민 가족) | 100개 | probe 질문 20개, STT 73개 |

사진은 build할 때 Pexels에서 내려받습니다.

## 실행 순서

```powershell
# 1. 평가 준비 (construct는 유료 OpenAI 호출, Neo4j 필요)
python -m testbed.pipeline --dataset family-week-100-five-members --phase all
# 2. 비용 확인 후 평가
python -m testbed.feature_eval --dataset family-week-100-five-members --feature all --dry-run
python -m testbed.feature_eval --dataset family-week-100-five-members --feature all
```

결과는 `testbed/output/<dataset_name>/` 아래에 쌓입니다.

- `manifest.json`, `images/`: build 결과
- `test.sqlite3`, `media/`, `database_state.json`: 평가용 test DB
- `pipeline_state.json`: 완료한 phase
- `feature_eval/<feature>.json`: 기능별 평가 보고서

## 테스트

```powershell
python -m pytest testbed
```

`testbed/pytest.ini`가 저장소 공통 pytest-django 설정을 끕니다. 테스트는 API를 호출하지 않습니다.

## 가족방 ID와 Graphiti

Graphiti 기억은 가족방 ID별 group(`family_<ID>`)에 저장되고, 개발 서버와 testbed가 같은 Neo4j를 쓸 수 있습니다. 그래서 test DB의 가족방 ID는 데이터셋 이름에서 계산한 1000 이상의 고정값을 씁니다. 데이터셋끼리, 그리고 개발 서버의 가족방과 기억이 섞이지 않습니다. config의 `family_id`로 직접 지정할 수도 있습니다.
