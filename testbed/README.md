# Graphiti 가족 피드 Testbed

이 폴더는 7일 동안 이어지는 가족 사건을 먼저 정의하고, 사건에 맞는 인물 중심 생활 사진을 붙여 피드 데이터셋을 만듭니다. 기본 `curated` 모드는 웹에서 사람이 직접 확인한 Pexels 사진 20장을 사용하므로 API 키가 필요하지 않습니다. 각 사건 줄기는 `core`, 여러 가족 구성원이 작성하는 `extension`/`reinforcement`/`update`/`distractor`, 마지막 날의 `probe`로 구성됩니다.

이 README는 실행 방법과 함께 config·catalog·사진·정답 label을 수정할 때 지켜야 할 규칙을 모두 담고 있습니다.

## 코드 경계와 파일 역할

데이터 생성·정답표·시각화 코드는 TalkDock에 의존하지 않습니다. Django와의 결합은 `adapters/talkdock_django.py` 한 파일에만 있으며, TalkDock backend는 이 폴더를 import하지 않습니다.

- `input/config.example.json`: 4인 가족의 실행 가능한 기본 예시
- `input/event_catalog.example.json`: 사건 줄기와 retrieval 정답 label 정의
- `input/curated_sources.example.json`: `feed_key`별로 사람이 확인한 사진과 출처 정의
- `dataset_builder.py`: config 검증, 사건 선택, 작성자·시각 배정, 사진 다운로드와 manifest 생성
- `pipeline.py`: build부터 probe seed까지 phase 순서와 상태를 관리
- `adapters/talkdock_django.py`: TalkDock Django 설정과 ORM에 접근하는 유일한 결합 지점
- `test_*.py`: 데이터와 phase 실행 경계의 불변 조건 검증
- `output/<dataset_name>/`: 실행할 때 생성되는 결과이며 Git에 포함하지 않음

## 데이터 생성

`input/config.example.json`을 복사해 구성원과 게시물 수를 바꿉니다.

- `members`: 2~9명. `owner`는 정확히 한 명이고 slot은 중복될 수 없습니다.
- `post_count`: 사건 줄기 수의 2배 이상이어야 하며, 최댓값은 선택한 줄기에 정의된 사건 수의 합입니다.
- `event_catalog`: 사용할 사건 catalog JSON 경로입니다.
- `thread_ids`: event catalog에서 사용할 사건 줄기의 ID 목록입니다.
- `author_policy`: 게시물 작성자 분배 규칙입니다. 생략하면 기존 `round_robin`을 사용합니다. `thread_owner_weighted`는 사건별 주 작성자를 정하고 `primary_author_ratio`만큼의 게시물을 맡깁니다. `probe_author`는 `mixed`, `primary`, `secondary` 중에서 선택하며 `seed`로 mixed 배치를 재현합니다.
- `download_images`: `false`이면 사건 계획과 정답표만 만듭니다.
- `image_providers`: 사용할 순서입니다. 기본값은 `curated`입니다. 자동 검색이 필요하면 `openverse`, `commons`, `pexels`도 사용할 수 있습니다.
- `curated_sources`: 사람이 고른 사진의 페이지·작가·다운로드 URL을 담은 JSON 파일입니다.
- `openverse_source`: 기본값은 인물 생활 사진이 많은 `flickr`입니다. 빈 문자열이면 Openverse 전체를 검색합니다.
- `openverse_licenses`: 허용할 공개 라이선스입니다. 기본값은 CC0, Public Domain, CC BY, CC BY-SA입니다.
- `openverse_api_token_env`: 선택적인 Openverse access token 환경변수 이름입니다. 익명 요청이 제한되는 환경에서 사용합니다.
- `pexels_api_key_env`: Pexels API 키를 읽을 환경변수 이름입니다. 키가 없으면 Pexels는 자동으로 건너뜁니다.
- `user_agent`: 이미지 API 정책에 맞는 프로젝트 식별자와 연락 가능한 URL 또는 이메일을 적습니다.

```powershell
Copy-Item testbed\input\config.example.json testbed\input\config.local.json
python testbed\dataset_builder.py --config testbed\input\config.local.json
```

Pexels fallback을 사용하려면 키를 JSON 파일에 넣지 말고 환경변수로 설정합니다.

```powershell
$env:PEXELS_API_KEY = "발급받은 API 키"
python testbed\dataset_builder.py --config testbed\input\config.local.json
```

Openverse에서 익명 요청을 제한하는 경우에도 토큰을 환경변수로 전달할 수 있습니다.

```powershell
$env:OPENVERSE_API_TOKEN = "발급받은 access token"
python testbed\dataset_builder.py --config testbed\input\config.local.json
```

결과는 `testbed/output/<dataset_name>/` 아래에 생성됩니다.

- `dataset_plan.json`: 사진 다운로드 전에 저장되는 사건 계획
- `manifest.json`: 사진 경로, 출처, 라이선스와 정답 라벨을 포함한 최종 데이터
- `images/`: 최대 1600px JPEG 사진

probe에는 `evaluation_question`, `required_memories`, `optional_memories`, `must_filter`가 들어 있습니다. `evaluation_question`은 현재 게시물만으로 답할 수 없고 과거 가족 기록이 필요한 질문이어야 합니다. `relationship_matrix`는 현재 애플리케이션의 관계 계산 규칙과 같습니다.

## Phase Pipeline

일반적인 실행은 `pipeline.py` 하나로 처리합니다. 각 phase는 독립적으로 다시 실행할 수 있고 `pipeline_state.json`에 완료 상태가 기록됩니다.

```text
build → seed-memory → construct → seed-probes → evaluate
```

전체 과정을 순서대로 실행하려면 OpenAI·Neo4j 환경변수를 설정한 뒤 다음 명령을 사용합니다.

```powershell
venv\Scripts\python.exe testbed\pipeline.py `
  --config testbed\input\config.example.json `
  --phase all
```

한 단계씩 실행할 수도 있습니다.

```powershell
venv\Scripts\python.exe testbed\pipeline.py --config testbed\input\config.example.json --phase build
venv\Scripts\python.exe testbed\pipeline.py --config testbed\input\config.example.json --phase seed-memory
venv\Scripts\python.exe testbed\pipeline.py --config testbed\input\config.example.json --phase construct
venv\Scripts\python.exe testbed\pipeline.py --config testbed\input\config.example.json --phase seed-probes
venv\Scripts\python.exe testbed\pipeline.py --config testbed\input\config.example.json --phase evaluate
```

연속된 일부 단계는 `--phase`를 반복해 실행합니다.

```powershell
venv\Scripts\python.exe testbed\pipeline.py `
  --config testbed\input\config.example.json `
  --phase seed-probes `
  --phase evaluate
```

Pipeline은 이전 phase가 완료되지 않았으면 다음 phase를 중단합니다. 외부에서 이미 같은 작업을 마쳤을 때만 `--force`로 이 검사를 건너뜁니다. `--skip-images`는 build 결과만 확인할 때 사용하며, 이 상태에서는 DB seed가 차단됩니다.

완료 상태와 주요 경로는 다음 파일에 저장됩니다.

```text
testbed/output/<dataset_name>/pipeline_state.json
testbed/output/<dataset_name>/database_state.json
testbed/output/<dataset_name>/evaluation.json
```

`evaluate`는 각 probe의 `evaluation_question`을 모든 가족 구성원의 관점에서 최신 backend의 `post_qa` 경로로 실행합니다. 입력에는 게시물 원문과 사진, 질문자 이름, 작성자와의 관계, 게시 시각이 포함됩니다. Graphiti가 반환한 source를 `database_state.json`의 post ID와 연결해 다음 지표를 계산합니다.

- `mean_required_recall`: 필수 memory label을 retrieval한 비율
- `mean_retrieval_source_precision`: required 또는 optional label을 제공한 source 비율
- `filter_leakage_case_rate`: `must_filter` label이 retrieval된 평가 case 비율
- `relationship_mention_rate`: 기대 관계 표현이 answer에 포함된 비율
- `search_rate`: QA 과정에서 실제 memory 검색을 실행한 비율
- `mean_answer_diversity`: 같은 질문에 대한 가족별 answer의 고유성

각 case의 question, query, retrieval memory, source feed, answer와 세부 판정도 `evaluation.json`에 함께 저장됩니다. 관계 표현은 자연스러운 답변에서 생략될 수 있으므로 `relationship_mention_rate`는 보조 지표로 해석합니다. `post_summary`는 최신 backend에서 Graphiti를 검색하지 않으므로 retrieval 평가에 사용하지 않습니다.

별도 TalkDock checkout을 대상으로 실행할 때는 pipeline에 backend 경로를 전달합니다.

```powershell
venv\Scripts\python.exe testbed\pipeline.py `
  --config testbed\input\config.example.json `
  --backend C:\path\to\talkdock\backend `
  --phase all
```

## 정답 추적

Graphiti 검색 source 이름은 `post_<DB id>`입니다. 시드 도구가 만든 `database_state.json`의 `post_ids`로 source를 `feed_key`로 되돌리고, 해당 feed의 `establishes`와 probe 정답 라벨을 비교할 수 있습니다.

관계 정확도는 같은 probe를 모든 구성원으로 조회한 뒤 다음처럼 계산합니다.

```text
예측 관계 == relationship_matrix[viewer_username][author_username]
```

caption에는 관계 정답 단어를 의도적으로 넣지 않아 단순 복사로 정답 처리되는 것을 줄였습니다.

## 테스트

```powershell
python -m pytest testbed -q
```

기본 사진 목록은 `input/curated_sources.example.json`에 저장합니다. 각 항목은 사건의 `feed_key`, Pexels 사진 페이지, 작가, 직접 다운로드 URL을 포함합니다. 생성기는 사진을 받은 뒤 최대 1600px JPEG로 정규화하고 Pexels License 및 출처를 manifest에 보존합니다. 자동 검색용 Openverse·Commons·Pexels 크롤러도 남아 있지만, 기본 데이터셋 생성에는 사용하지 않습니다.

## 데이터셋 수정 범위

다음 변경은 config만 수정합니다.

- 가족 이름, 시작일, 초대 코드와 비밀번호
- 구성원 이름, 성별, generation과 부모/배우자 연결
- 기존 catalog 범위 안의 `thread_ids`와 `post_count`
- 출력 데이터셋 이름과 작성자 배정 정책

다음 변경은 catalog와 사진 정답표까지 함께 수정합니다.

- 선택한 catalog의 가용 개수보다 큰 `post_count`
- 새로운 사건 줄기 또는 event 추가
- 기존 사건의 의미나 정답 memory label 변경

`post_count`를 바꿀 때마다 catalog를 다시 쓰지 않습니다. 충분히 큰 catalog를 유지하고 config가 그 부분집합을 선택하게 합니다.

## Config 작성 규칙

`members`는 2명 이상이며 `owner_username`으로 방 관리자를 지정합니다. `generation`은 가계도 배치용 정수입니다. `parents`의 `parent_id`/`child_id`, `partnerships`의 `first_id`/`second_id`에는 구성원의 username을 사용합니다. 관계는 앱과 동일한 tree 탐색 함수로 계산합니다.

`username`은 데이터셋 안에서 고유해야 합니다. `gender`는 `female`, `male`, `unknown` 중 하나입니다. caption의 구성원 치환자는 `{m0}`, `{m1}`처럼 사용하며 구성원 수에 따라 순환 배정됩니다.

선택한 각 thread에는 core와 probe가 항상 한 개씩 들어갑니다.

```text
선택한 thread 수 × 2 <= post_count <= 선택한 thread의 전체 event 수
```

같은 설정을 반복 실행할 때 충돌하지 않도록 `dataset_name`과 `invite_code`를 데이터셋별로 고유하게 지정합니다. API token이나 비밀 키는 JSON에 넣지 않고 환경변수로 전달합니다.

## 사건 줄기 설계

각 thread에는 정확히 한 개의 `core`와 한 개의 `probe`가 있어야 합니다. 그 사이에 평가 목적에 맞는 branch event를 배치합니다.

- `core`: 사건 줄기의 기준 사실을 처음 설정
- `extension`: 관련된 새 사실 추가
- `reinforcement`: 핵심 사실을 다른 상황이나 작성자가 다시 확인
- `update`: 현재 사실을 바꾸고 이전 label을 `invalidates`에 기록
- `distractor`: 표현은 비슷하지만 probe 답에 사용하면 안 되는 별도 사실
- `probe`: 게시물에 대한 후속 질문의 retrieval과 answer를 평가할 마지막 날의 입력

Event ID는 catalog 전체에서 고유한 `<thread-id>-<event-name>` 형식으로 만듭니다. Memory label은 thread 접두사가 있는 대문자 snake case를 사용하고 서로 다른 사실에 같은 label을 재사용하지 않습니다.

```json
{
  "id": "lunchbox-probe",
  "kind": "probe",
  "caption": "금요일 아침 도시락을 챙겨서 사진을 남겼어요.",
  "image_query": "person holding homemade lunchbox in morning",
  "evaluation_question": "최종 도시락 메뉴는 무엇으로 바뀌었고, 준비하기로 한 사람은 누구야?",
  "required_memories": ["LUNCHBOX_MENU_CURRENT", "LUNCHBOX_COOK"],
  "optional_memories": [],
  "must_filter": ["LUNCHBOX_MENU", "OTHER_GIMBAP"]
}
```

## 정답 Label 규칙

- `establishes`: 해당 feed가 기억에 추가해야 하는 원자적 사실
- `required_memories`: probe 질문에 답하려면 반드시 필요한 현재 사실
- `optional_memories`: 반영되면 자연스럽지만 없어도 정답인 사실
- `must_filter`: 검색되더라도 answer에 사용하면 안 되는 사실
- `invalidates`: update 전에 존재했지만 더는 유효하지 않은 label

`required_memories`와 `must_filter`는 선택된 history에 실제로 존재해야 합니다. `must_filter`에는 같은 단어를 공유하는 distractor와 update로 무효화된 과거 사실을 우선 포함합니다. Probe caption에는 정답 관계나 과거 사실을 그대로 쓰지 않습니다. `evaluation_question`은 `required_memories`를 직접 요구하되 정답 자체를 질문에 넣지 않습니다.

## 사건과 작성자 선택

생성기는 모든 thread에서 core와 probe를 먼저 예약한 뒤 branch event를 thread별로 번갈아 추가합니다. 기존 사건의 우선순위는 `dataset_builder.py`의 `BENCHMARK_ORDER`가 결정하며, 표에 없는 thread는 catalog 순서를 사용합니다.

기본 `round_robin` 작성자 정책은 여러 구성원이 사건에 참여하게 합니다. `thread_owner_weighted` 정책은 사건별 주 작성자를 두고 `primary_author_ratio`만큼의 게시물을 맡깁니다. 각 thread에는 최소 두 명의 작성자가 있어야 하며 distractor는 주 작성자와 분리합니다.

구성원별 personalization은 같은 probe를 모든 viewer로 실행하고 다음 관계 정답을 사용합니다.

```text
relationship_matrix[viewer_username][probe.author_username]
```

Caption에는 `아빠`, `엄마`, `딸`처럼 viewer에 따라 달라지는 관계 정답을 직접 쓰지 않고 이름이나 중립적인 표현을 사용합니다.

## 사진 추가 규칙

기본값은 사람이 확인한 `curated` 사진입니다. 새 event마다 curated source 파일에 같은 `feed_key`의 항목을 추가합니다.

### Agent가 Curated Sources를 채우는 방법

새 config 또는 event catalog를 만든 뒤에는 agent가 curated source 파일을 자동으로 완성해야 합니다. 이 작업은 이미지 검색 API를 무작위로 호출하는 crawler 작업이 아니라, agent가 각 사건과 실제 검색 결과를 직접 비교해 고르는 과정입니다.

Agent는 다음 순서로 작업합니다.

1. Config의 `thread_ids`와 `post_count`를 읽습니다.
2. config의 `event_catalog`에서 실제로 선택될 event와 `feed_key`를 계산합니다.
3. 각 event의 `caption`, `image_query`, `kind`를 함께 읽습니다.
4. 웹 이미지 검색으로 사건의 대상과 행동이 보이는 사진을 찾습니다.
5. 원본 사진 페이지를 열어 작가, 라이선스와 직접 이미지 URL을 확인합니다.
6. Config의 `curated_sources`가 가리키는 JSON 파일에 event당 한 항목을 작성합니다.
7. 선택된 모든 `feed_key`가 정확히 한 번씩 포함됐는지 검사합니다.
8. URL 접근, 이미지 형식, 해상도와 중복 여부를 검증합니다.

검색 결과의 제목이나 썸네일만 보고 출처 정보를 추측해서는 안 됩니다. 존재하지 않는 `page_id`, 작가, URL 또는 라이선스를 만들어 넣지 않으며, 원본 페이지와 직접 이미지 URL을 실제로 열어 확인해야 합니다. 적절한 사진을 찾지 못하면 임의의 사진을 넣지 않고 해당 `feed_key`를 미완료로 보고합니다.

```json
{
  "feed_key": "lunchbox-core",
  "page_id": 12345678,
  "title": "Family member preparing a lunchbox at home",
  "artist": "Photographer Name",
  "page_url": "https://www.pexels.com/photo/example-12345678/",
  "image_url": "https://images.pexels.com/photos/12345678/example.jpeg"
}
```

사진을 직접 열어 다음을 확인합니다.

- caption의 핵심 대상과 행동이 보임
- 가능하면 사람이 포함되고 지나치게 연출된 제품 사진이 아님
- 사건과 무관한 강한 정치·재난·시위 맥락이 없음
- 같은 사진을 여러 `feed_key`에 재사용하지 않음
- 원본 페이지, 작가와 라이선스를 확인할 수 있음
- 서로 다른 사진의 얼굴을 동일 인물이라고 주장하지 않음

Agent에게는 다음처럼 요청할 수 있습니다.

```text
testbed/README.md의 사진 추가 규칙에 따라 이 config의 curated sources를 완성해줘.

- config의 thread_ids와 post_count로 실제 선택되는 event를 먼저 계산
- event_catalog의 caption과 image_query를 기준으로 사진 검색
- 사람이 포함된 자연스러운 생활 사진을 우선 선택
- 원본 페이지, 작가, 라이선스, 직접 이미지 URL을 실제로 확인
- feed_key 누락과 사진 중복이 없도록 JSON 작성
- URL과 이미지 파일을 검증하고 테스트까지 실행
```

## 변경 절차와 필수 검증

1. 평가 목표, 가족 구성, thread 수와 `post_count`를 결정합니다.
2. 기존 catalog에서 충족 가능한지 계산합니다.
3. 가능하면 config만 만들고, 부족하면 catalog와 사진 출처를 함께 확장합니다.
4. Builder로 데이터셋을 생성합니다.
5. 자동 테스트와 manifest 무결성을 확인합니다.
6. Retrieval 평가는 memory phase, Graphiti construction, probes phase 순서로 실행합니다.

```powershell
python -m pytest testbed -q
python testbed\dataset_builder.py --config testbed\input\config.example.json
```

생성 후 다음 항목을 확인합니다.

- event 수가 `post_count`와 일치함
- 각 thread에 core와 probe가 정확히 하나씩 존재함
- 각 thread에 작성자가 두 명 이상 존재함
- probe가 7일째에 배치됨
- 모든 `required_memories`와 `must_filter`가 선택된 history에 존재함
- 모든 event에 이미지가 있고 사진 출처가 중복되지 않음
- 이미지 파일을 실제로 열 수 있고 짧은 변이 400px 이상임
- 사진 내용이 caption과 의미상 일치함

새 config나 사건을 agent에게 요청할 때는 이 README의 규칙을 따르게 하고, 필요하면 catalog·작성자 우선순위·사진 출처와 테스트까지 함께 갱신하도록 요청합니다.
