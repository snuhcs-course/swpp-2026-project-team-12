# AI 기능별 평가

[평가 준비 pipeline](../pipeline/README.md)이 만든 데이터셋 test DB로 AI 기능 5개를 평가합니다. 가족 기록 검색(family history)은 [memoryqa_scaling](../memoryqa_scaling/README.md)에서 평가하므로 여기서는 다루지 않습니다. 데이터셋을 새로 만들지 않고, 같은 게시물·작성 시각·가족 관계표·기억 label을 각 기능의 입력과 정답 근거로 씁니다.

| 기능 | 묶음 | case | 규칙 기반 채점 | LLM judge |
|---|---|---|---|---|
| `description` | 검색 없음 | test DB의 게시물마다 1개 | 정답 사실 포함률, 금지어, 3~5문장 | 지어낸 내용, 캡션 충실도, 사진 세부 정보, 사진과 원문 구분 |
| `summary` | 검색 없음 | 게시물 × 작성자가 아닌 가족 | 숫자·이름 보존, 관계 호칭, 앱 관계 계산과 manifest 일치, 존댓말, 문장 수(참고용) | 사실 추가 여부, 호칭, 말투 |
| `digest` | 검색 없음 | 게시 날짜마다 1개 | 사실 포함률, 작성자별 한 문단, 1~3문장, 다른 날 캡션 복사 | 누락, 정확성, 다른 게시글·날짜 혼합, 압축 |
| `post_qa` | 판단 → 검색 → 답변 | probe × 가족 전원 | 검색 판단 정답, 정답 키워드, 금지어, required recall, source precision, 옛 기억 검색 여부(참고용), 가족별 답변 다양성 | 질문에 답했는지, 정답 여부, 옛 기록·지어낸 사실, 검색어 품질 |
| `stt` | 판단 → 검색 → 답변 | manifest의 `voice_replies` | 모범 변환 일치, 유지·삭제 단어, 전달 표현 제거, 숫자·부정어 보존, 한국어 유지 | 뜻 보존, 덧붙임, 전달 문구 제거, 이름 교정(`misheard`), injection 무시 |

숫자·이름·날짜·검색된 기억처럼 문자열과 label로 판정할 수 있는 항목은 규칙 기반으로만 채점합니다. judge는 뜻과 말투를 읽어야 하는 항목만 판정합니다.

judge 기준은 가족이 사실을 잘못 알게 되거나 기능의 목적을 놓친 경우만 실패로 봅니다. 표현·문장부호 차이, 사소한 배경 생략, "~같아요"처럼 추측임을 드러낸 해석, 앱 관계명과 같은 뜻의 자연스러운 호칭(3대 조상→증조할머니 등)은 실패 사유가 아닙니다. 옛 기억이 검색되는 것은 변경 질문에 필요하므로 `retrieval_pass`에 반영하지 않고, 답변이 옛 기록을 현재처럼 말했는지는 judge의 `no_stale_or_invented`로 봅니다. 기준 문구가 바뀌면 judge 캐시 key가 달라지므로 `--reuse-outputs`로 다시 채점하면 judge만 새로 호출됩니다.

## 파일 역할

- `cases.py`: manifest와 정답 파일에서 기능별 case를 만듭니다. Django와 네트워크를 사용하지 않습니다.
- `checks.py`: 규칙 기반 채점 함수입니다.
- `judge.py`: 기능별 평가 기준, judge가 받는 입력, 디스크 캐시를 담당합니다.
- `runners.py`: 앱과 같은 경로로 backend 기능을 호출합니다. Django 설정 뒤에만 import합니다.
- `evaluate.py`: CLI입니다. pipeline 상태 확인, 실행, 채점, 기준치 비교, 보고서 저장을 맡습니다.
- `query_eval.py`: post_qa·stt 보고서에 저장된 검색어로 Graphiti 검색만 다시 실행해, 검색어 품질(budget 전 recall, 질문 원문 baseline)과 `select_budget`에서 잘린 몫을 나눠 봅니다. embedding 호출만 하고 LLM은 부르지 않습니다. `python -m testbed.feature_eval.query_eval --dataset <name>` → `feature_eval/queries.json`
- 기억 label 매핑(`post_<ID>` → feed_key → label)은 `common/labels.py`를 씁니다.

## 실행 순서

먼저 평가 준비 pipeline으로 test DB를 준비합니다. 기능마다 필요한 phase가 다릅니다.

| 기능 | 필요한 phase |
|---|---|
| `description`, `summary`, `digest` | `seed-memory` (`construct` 후에는 저장된 description을 재사용) |
| `stt` | `construct` |
| `post_qa` | `seed-probes` |

```powershell
python -m testbed.pipeline --dataset family-week-100-five-members --phase all

# case 수만 확인 (API 호출 없음)
python -m testbed.feature_eval --dataset family-week-100-five-members --feature all --dry-run
# 규칙 기반 채점만
python -m testbed.feature_eval --dataset family-week-100-five-members --feature stt --no-judge
# judge 포함
python -m testbed.feature_eval --dataset family-week-100-five-members --feature all
```

- 결과는 `testbed/output/<dataset_name>/feature_eval/<feature>.json`에 case별 출력, 규칙 채점, judge 판정과 함께 저장됩니다. 이 폴더는 Git에 포함하지 않습니다.
- `--reuse-outputs`: 이전 보고서의 기능 출력을 재사용합니다. 채점 기준이나 judge만 바꿔 다시 볼 때 기능 호출 비용이 들지 않습니다.
- `--limit N`: 기능마다 앞의 N개 case만 실행합니다. 처음 연결을 확인할 때 씁니다.
- `--regenerate-descriptions`: construction 때 저장된 description 대신 새로 생성합니다. 프롬프트를 바꾼 뒤 비교할 때 씁니다.
- 한 case가 실패해도 나머지는 계속 실행하고, 실패한 case는 `error`와 `error_count`로 남습니다.

## Judge

- 기본 모델은 `JUDGE_AI_MODEL`, 없으면 `DEFAULT_AI_MODEL`입니다. 앱과 같은 모델로 채점하면 자기 출력을 후하게 평가할 수 있으므로 가능하면 `JUDGE_AI_MODEL`을 다른 모델로 지정하세요. `JUDGE_AI_REASONING_EFFORT`로 reasoning 강도를 정할 수 있습니다.
- 기준마다 `pass`와 한 문장 `reason`을 strict JSON schema로 받습니다. 애매하면 fail로 판정하도록 지시합니다.
- 모델·기준·입력·출력·사진 hash가 같으면 `feature_eval/judge_cache/`의 판정을 재사용합니다.
- judge 점수를 보고서에 쓰기 전에 기능마다 10~20건을 사람이 채점해 judge 판정과 일치하는지 확인하세요.

## 정답 파일

데이터셋 폴더의 `gold.json`(`datasets/<이름>/gold.json`)은 manifest만으로 알 수 없는 정답을 보충합니다. 모든 항목은 선택입니다.

```json
{
  "description": {"clinic-core": {"must_include": [["아침"], ["1회", "한 번"]], "must_not_include": []}},
  "summary": {"birthday-train": {"must_include": [["기차"]], "must_not_include": []}},
  "digest": {"2026-10-26": {"must_include": [["상추"]], "must_not_include": ["떡볶이"]}},
  "post_qa": {"clinic-probe": {"expects_search": true, "answer_units": [["13일", "금요일"]], "forbidden_answer_strings": ["12일"]}}
}
```

- `must_include`/`answer_units`는 사실 하나를 대안 표기 목록으로 적습니다. 공백은 무시하고 비교합니다.
- 정답 파일이 없으면 캡션의 숫자와 가족 이름을 `must_include`로 쓰고, probe의 `expects_search`는 `required_memories` 또는 `optional_memories`가 있으면 `true`입니다.
- `stt` 정답은 데이터셋 event catalog의 `voice_replies`에 있습니다. catalog의 `history_questions`는 데이터로 남아 있지만 이 평가에서는 쓰지 않습니다.
- case에 `type`이 있으면 보고서의 `metrics_by_type`에 유형별 지표가 따로 저장됩니다. STT 유형은 다음과 같습니다.

| type | 확인하는 것 |
|---|---|
| `relay` | "~라고 전해줘"를 가족에게 직접 하는 말로 바꾸는지 |
| `direct` | 이미 직접 하는 말은 고치지 않는지 |
| `negation` | 안·못·말고·않·아니가 남는지 |
| `number` | 시각·개수·크기가 그대로인지 |
| `name` | 가족만 쓰는 이름·장소를 바꾸거나 합치지 않는지, 전달 대상이 작성자와 다를 때 작성자로 바꾸지 않는지 |
| `condition` | "~하면" 조건이 남는지 |
| `register` | 말하는 사람의 반말·존댓말을 유지하는지 |
| `misheard` | 음성 인식이 틀린 가족 이름을 기록에 있는 이름으로 고치는지 (현재 프롬프트에는 교정 규칙이 없음). 이름을 그대로 둔 것은 `meaning_kept`가 아니라 `name_corrected`에서만 실패 |
| `injection` | 말 속의 지시를 따르지 않고 댓글로만 변환하는지. 지시문을 글자로 남기거나 빼는 것은 둘 다 허용 |
| `misheard_word` | 이름이 아닌 단어(장소·음식·물건)의 인식 오류를 원문이나 가족 기록으로 고치는지. `word_corrected`로 채점 |
| `keep_intended` | 유행어·줄임말·사투리·별명을 인식 오류로 보고 고치지 않는지. 과교정 방지용, `intended_kept`로 채점 |

STT 문항은 `family-week-100-five-members`에 73개 있습니다.

## 합격 기준

데이터셋 폴더에 `thresholds.json`을 두면 기능별 지표를 기준치와 비교해 보고서의 `thresholds`에 결과를 남깁니다.

```json
{
  "post_qa": {
    "required_recall": {"operator": ">=", "target": 0.8, "rationale": "필요한 기억을 대부분 찾아야 함"},
    "filter_leaked_rate": {"operator": "<=", "target": 0.1}
  }
}
```

## 테스트

```powershell
python -m pytest testbed
```
