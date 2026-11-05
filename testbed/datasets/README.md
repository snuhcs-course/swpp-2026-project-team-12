# 데이터셋

데이터셋 하나는 7일 동안 이어지는 가족 사건, 사건마다 붙는 정답 label, 사람이 확인한 사진으로 이루어집니다. 사건 줄기(thread)는 기준 사실을 세우는 `core`, 여러 가족이 이어 쓰는 `extension`/`reinforcement`/`update`/`distractor`, 마지막 날 질문을 받는 `probe`로 구성됩니다.

## 폴더 구성

```text
datasets/<이름>/
  config.json            가족, 게시물 수, 사용할 사건 줄기, 사진 공급 방식
  event_catalog.json     사건 줄기, 정답 label, 기능별 평가 문항
  curated_sources.json   feed_key마다 사람이 확인한 사진과 출처
  images/                저장소에 넣은 사진 (선택)
  gold.json              feature_eval 기능별 정답 보충 (선택)
  thresholds.json        feature_eval 합격 기준 (선택)
```

config 안의 `event_catalog`, `curated_sources`, 사진의 `local_path`는 모두 그 config가 있는 폴더 기준 상대 경로입니다. 개인 실험용 config는 같은 폴더에 `config.local.json`으로 만들면 Git에 올라가지 않습니다.

## Build

```powershell
python -m testbed.builder --dataset example
python -m testbed.builder --dataset testbed\datasets\example\config.local.json --output testbed\output\my-test
```

결과는 `testbed/output/<dataset_name>/`에 생깁니다.

- `dataset_plan.json`: 사진을 받기 전에 저장하는 사건 계획
- `manifest.json`: 사진 경로, 출처, 라이선스, 정답 label을 포함한 최종 데이터
- `images/`: 최대 1600px JPEG 사진

평가용 test DB와 Graphiti 기억은 [평가 준비 pipeline](../pipeline/README.md) pipeline이 이 결과로 만듭니다.

## 앱 DB에 넣기

서버를 띄웠을 때 데이터셋 가족이 보이게 하려면 build 뒤에 앱 DB(기본값 `backend/db.sqlite3`, `backend/media`)에 게시물·댓글·지난 오늘의 질문을 한 번에 넣습니다. AI 호출은 없고, 다시 실행하면 이미 있는 행은 건너뜁니다. 앱 DB에서는 가족방 ID를 앱이 정합니다.

```powershell
python -m testbed.builder --dataset example
python -m testbed.builder.seed_app --dataset example
# 공유용 DB를 따로 만들 때
python -m testbed.builder.seed_app --dataset example --database share\db.sqlite3 --media-root share\media
```

로그인은 config의 `members[].username`과 `default_password`로 합니다.

## config 항목

- `dataset_name`, `invite_code`: 데이터셋마다 고유하게 지정합니다.
- `members`: 2~9명. `owner_username`으로 방장을 지정합니다. `username`은 고유해야 하고 `gender`는 `female`, `male`, `unknown` 중 하나입니다. `generation`은 가계도 배치용 정수입니다.
- `parents`(`parent_id`/`child_id`), `partnerships`(`first_id`/`second_id`): 구성원 username으로 가계도를 적습니다. 관계는 앱과 같은 tree 탐색 함수로 계산합니다.
- `thread_ids`, `post_count`: catalog에서 쓸 사건 줄기와 게시물 수입니다. `선택한 thread 수 × 2 <= post_count <= 선택한 thread의 전체 event 수`
- `author_policy`: 생략하면 `round_robin`입니다. `thread_owner_weighted`는 사건별 주 작성자에게 `primary_author_ratio`만큼의 게시물을 맡깁니다. `probe_author`는 `mixed`, `primary`, `secondary` 중 하나이고 `seed`로 mixed 배치를 재현합니다.
- `family_id`: test DB 가족방 ID를 직접 지정할 때만 씁니다. 생략하면 데이터셋 이름에서 계산한 1000 이상의 값을 씁니다.
- `download_images`: `false`이면 사건 계획과 정답표만 만듭니다.
- `image_providers`: 기본값은 `curated`입니다. 자동 검색이 필요하면 `openverse`, `commons`, `pexels`도 쓸 수 있지만 기본 데이터셋에는 쓰지 않습니다.
- `openverse_source`, `openverse_licenses`, `openverse_api_token_env`, `pexels_api_key_env`: 자동 검색 공급자 설정입니다. API 키는 JSON에 넣지 않고 환경변수로 전달합니다.
- `user_agent`: 이미지 요청에 쓰는 프로젝트 식별자와 연락 가능한 URL입니다.

config만 바꿔도 되는 변경은 가족 이름·구성원·가계도·시작일·비밀번호, catalog 범위 안의 `thread_ids`/`post_count`, 작성자 정책입니다. catalog보다 큰 `post_count`, 새 사건 줄기, 기존 사건의 의미나 정답 label 변경은 catalog와 사진 출처까지 함께 고칩니다. `post_count`를 바꿀 때마다 catalog를 다시 쓰지 않고, 충분히 큰 catalog에서 config가 부분집합을 고르게 합니다.

## 사건 줄기 설계

각 thread에는 정확히 한 개의 `core`와 한 개의 `probe`가 있습니다.

- `core`: 사건 줄기의 기준 사실을 처음 세웁니다.
- `extension`: 관련된 새 사실을 더합니다.
- `reinforcement`: 핵심 사실을 다른 상황이나 작성자가 다시 확인합니다.
- `update`: 현재 사실을 바꾸고 이전 label을 `invalidates`에 적습니다.
- `distractor`: 표현은 비슷하지만 probe 답에 쓰면 안 되는 별도 사실입니다.
- `probe`: 마지막 날 게시물로, 후속 질문의 검색과 답변을 평가합니다.

Event ID는 catalog 전체에서 고유한 `<thread-id>-<event-name>` 형식입니다. Memory label은 thread 접두사가 붙은 대문자 snake case이고, 서로 다른 사실에 같은 label을 쓰지 않습니다. caption의 구성원은 `{m0}`, `{m1}`처럼 쓰고 구성원 수에 따라 순환 배정됩니다.

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

### 정답 label

- `establishes`: 그 게시물이 기억에 더해야 하는 원자적 사실
- `required_memories`: probe 질문에 답하려면 반드시 필요한 현재 사실
- `optional_memories`: 있으면 자연스럽지만 없어도 정답인 사실
- `must_filter`: 검색되더라도 답에 쓰면 안 되는 사실
- `invalidates`: update 전에 있었지만 더는 유효하지 않은 label

`required_memories`와 `must_filter`는 선택된 history에 실제로 있어야 합니다. `must_filter`에는 같은 단어를 공유하는 distractor와 update로 무효화된 과거 사실을 우선 넣습니다. probe caption에는 정답 관계나 과거 사실을 그대로 쓰지 않고, `evaluation_question`은 정답 자체를 질문에 넣지 않습니다. caption에는 `아빠`, `엄마`, `딸`처럼 읽는 사람마다 달라지는 관계 단어 대신 이름이나 중립 표현을 씁니다.

### 사건과 작성자 선택

생성기는 모든 thread에서 core와 probe를 먼저 예약한 뒤 나머지 event를 thread별로 번갈아 더합니다. 기존 사건의 우선순위는 `builder/dataset_builder.py`의 `BENCHMARK_ORDER`가 정하고, 표에 없는 thread는 catalog 순서를 씁니다. 각 thread에는 작성자가 두 명 이상 있어야 하고 distractor는 주 작성자와 분리합니다.

### 작성자·시각을 고정한 주간 데이터셋

실제 가족 피드처럼 손으로 짠 일주일이 필요하면 event에 다음 선택 필드를 씁니다. 생략하면 자동 배정을 씁니다.

- `author`: `m0`, `m1` 같은 구성원 slot. `author_policy`보다 우선합니다.
- `day`, `time`: `start_date`로부터의 일수(0~6)와 `"HH:MM"`(KST). 둘을 함께 지정합니다. 하나라도 지정하면 history는 게시 시각 순으로 번호를 다시 매기고, probe는 그 뒤에 둡니다.
- `photos`: 사진 수(기본 1). `0`이면 글만 있는 게시물이고, 2 이상이면 curated source에 `<feed_key>#2`, `#3` 항목을 더합니다.

### 기능 평가 문항과 앱 화면용 데이터

catalog 최상위에 다음 섹션을 둘 수 있습니다. 모두 `{m0}` 치환과 slot 해석을 거쳐 manifest에 복사됩니다.

- `voice_replies`: STT 보정 문항. `speaker`, `feed_key`, `recognized`(인식된 말), `expected`(모범 변환), `must_keep`, `must_remove`, `type`, `note`를 적습니다. `type`별 의미는 [feature_eval README](../feature_eval/README.md#정답-파일)에 있습니다.
- `history_questions`: 가족 기록 질문. `asker`, `question`, `answerability`(answerable, unanswerable, ambiguous), `required_memories`, `must_filter`, `answer_units`, `forbidden_answer_strings`를 적습니다.
- `comments`, `daily_questions`: 게시물 댓글과 지난 오늘의 질문·답변. 앱 화면에만 쓰이고 Graphiti 구성과 digest에는 들어가지 않습니다. 음성 댓글은 `source: "voice"`와 함께 `recognized`와 변환된 `text`를 적습니다.

문항에 쓴 label과 `feed_key`는 선택된 history에 있어야 build가 통과합니다.

## 사진

기본값은 사람이 확인한 `curated` 사진입니다. event마다(사진이 여러 장이면 `#2`, `#3`까지) curated source 항목이 하나씩 있어야 합니다.

```json
{
  "feed_key": "lunchbox-core",
  "page_id": 12345678,
  "title": "Family member preparing a lunchbox at home",
  "artist": "Photographer Name",
  "page_url": "https://www.pexels.com/photo/example-12345678/",
  "image_url": "https://images.pexels.com/photos/12345678/example.jpeg",
  "local_path": "images/lunchbox-core.jpg"
}
```

- `local_path`가 있으면 내려받지 않고 데이터셋 폴더의 파일을 씁니다. `page_url`이 함께 있으면 Pexels 출처와 라이선스를 그대로 manifest에 남깁니다.
- 사진 속 글자가 정답 label과 정확히 맞아야 하는 처방전·예약 문자·기차표·시간표 등은 직접 그린 이미지를 씁니다. `image_url` 대신 `local_path`, `artist`, `license`를 적습니다.
- 생성기는 사진을 최대 1600px JPEG로 정규화하고 짧은 변이 400px보다 작으면 제외합니다.

Pexels 사진은 Pexels License에 따라 팀 내부 테스트용으로 쓰고, 사진만 따로 재배포하지 않습니다.

### Agent가 curated source를 채우는 방법

새 config나 catalog를 만든 뒤 agent에게 curated source를 채우게 할 때는 crawler를 무작위로 돌리지 않고, 각 사건과 실제 검색 결과를 직접 비교해 고르게 합니다.

1. config의 `thread_ids`와 `post_count`로 실제 선택될 event와 `feed_key`를 계산합니다.
2. 각 event의 `caption`, `image_query`, `kind`를 함께 읽습니다.
3. 웹 이미지 검색으로 사건의 대상과 행동이 보이는 사진을 찾습니다.
4. 원본 사진 페이지를 열어 작가, 라이선스, 직접 이미지 URL을 확인합니다.
5. event당 한 항목을 쓰고, 모든 `feed_key`가 정확히 한 번씩 들어갔는지 검사합니다.
6. URL 접근, 이미지 형식, 해상도, 중복을 검증합니다.

검색 결과의 제목이나 썸네일만 보고 출처를 추측하지 않습니다. 존재하지 않는 `page_id`, 작가, URL, 라이선스를 만들지 않고, 적절한 사진을 찾지 못하면 그 `feed_key`를 미완료로 보고합니다. 사진은 다음을 만족해야 합니다.

- caption의 핵심 대상과 행동이 보임
- 가능하면 사람이 들어 있고 지나치게 연출된 제품 사진이 아님
- 사건과 무관한 정치·재난·시위 맥락이 없음
- 같은 사진을 여러 `feed_key`에 재사용하지 않음
- 원본 페이지, 작가, 라이선스를 확인할 수 있음
- 서로 다른 사진의 얼굴을 같은 인물이라고 주장하지 않음

## 변경 절차와 검증

1. 평가 목표, 가족 구성, thread 수와 `post_count`를 정합니다.
2. 기존 catalog로 충분한지 계산합니다. 충분하면 config만 만들고, 부족하면 catalog와 사진 출처를 함께 늘립니다.
3. build하고 테스트를 실행합니다.

```powershell
python -m pytest testbed
python -m testbed.builder --dataset <이름>
```

build 뒤에 확인할 항목입니다.

- event 수가 `post_count`와 같음
- 각 thread에 core와 probe가 정확히 하나씩 있음
- 각 thread에 작성자가 두 명 이상 있음
- probe가 마지막 날에 있음
- 모든 `required_memories`와 `must_filter`가 선택된 history에 있음
- 모든 사진 파일이 열리고 출처가 중복되지 않음
- 사진 내용이 caption과 의미상 맞음
