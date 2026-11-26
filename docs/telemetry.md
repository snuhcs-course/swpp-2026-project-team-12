# TalkDock 텔레메트리 요구사항 및 명세

**범위**는 Android 앱부터 Linux 서버의 nginx·Waitress·Django, 검색·construction·음성 처리·푸시까지다. API 서버는 **nginx → Waitress → Django** 구성을 기준으로 한다. 아래 항목은 구현·설정해야 할 요구사항이며, 기존 FCM 연결만으로 충족된 것으로 보지 않는다.

## 1. 요구사항

| ID | 항목 | 요구사항 및 집계 기준 |
|---|---|---|
| TEL-01 | **ANR** | 최근 7일 운영 세션의 **ANR 발생률을 1% 미만**으로 유지한다. Android 11 이상에서 Crashlytics 수집이 활성화된 세션을 대상으로 `ANR이 1회 이상 발생한 세션 수 ÷ 전체 대상 세션 수 × 100`을 계산한다. |
| TEL-02 | **크래시 보고** | 치명적 크래시의 발생 시각, 앱 버전, Android 버전, 기기 모델, 예외 유형, 스택 트레이스와 직전 화면·기능을 조회할 수 있어야 한다. |
| TEL-03 | **기능 사용량** | 기능별 시작 건수, 완료 건수, 완료율을 집계한다. 사용 횟수는 기능별 고유 `operation_id` 수로 계산한다. 같은 실행의 재시도는 동일한 ID를 사용한다. 완료는 해당 기능의 마지막 단계가 성공한 경우로 정의하며, 서버 저장 성공과 앱 화면 반영 성공을 구분한다. |
| TEL-04 | **응답 시간** | 앱의 API 요청 시간과 결과 표시까지 걸린 시간, nginx의 전체·upstream 시간, Django의 처리 시간을 측정한다. 계층·API·결과별로 건수와 p50·p95를 집계한다. |
| TEL-05 | **서버 상태** | 요청량, HTTP 오류율, 호스트·서비스별 CPU·메모리와 디스크 사용량, 검색 큐·construction 미처리량·푸시 큐의 건수와 대기 시간, 서비스 상태와 재시작 이력을 확인할 수 있어야 한다. |
| TEL-06 | **장애 추적** | 사용자 동작에서 시작해 앱·nginx·Django·워커 로그를 조회하고, 실패 단계와 원인을 확인할 수 있어야 한다. |
| TEL-07 | **웹 대시보드** | 서버에서 수집한 로그·지표를 시각화한 HTML 기반 웹 대시보드를 제공한다. 운영자는 SSH 포트 포워딩을 통해 로컬 컴퓨터의 브라우저에서 기간·서비스·API·결과별 현황과 ID별 상세 로그를 조회할 수 있어야 한다. |

## 2. Firebase 및 수집 준비

기존 푸시용 Firebase 프로젝트와 Android 앱 등록을 재사용한다. `run_push_worker`는 **FCM 발송용**이며, 앱 텔레메트리를 수집하는 프로세스가 아니다.

| 항목 | 필요한 설정·구현 |
|---|---|
| **Android 공통** | 배포 패키지와 일치하는 기존 `google-services.json` 및 Google Services Gradle 플러그인 적용을 확인한다. Firebase Android BoM으로 Messaging·Crashlytics·Analytics SDK 버전을 함께 관리한다. 데모 패키지를 사용하면 해당 패키지의 Firebase 앱 등록·설정도 확인한다. |
| **Crashlytics** | `firebase-crashlytics` SDK와 Crashlytics Gradle 플러그인을 추가한다. 수집 활성화 상태를 확인하고 테스트 크래시·ANR을 보고한다. 직전 화면·기능은 화면 이벤트와 허용된 custom keys로 남긴다. |
| **Analytics** | Firebase 콘솔의 프로젝트 설정 → 통합에서 Google Analytics 연결·활성화를 확인하고, 앱에 `firebase-analytics` SDK를 추가한다. 자동 수집만으로 기능별 계측을 대체하지 않으며, 아래 이벤트를 명시적으로 기록한다. |
| **BigQuery** | Crashlytics 내보내기와 **Include sessions**, Google Analytics 내보내기를 각각 활성화한다. ANR 집계에는 `firebase_crashlytics`와 `firebase_sessions`를 사용하고, 기능별 중복 제거·완료율·시간 분포는 Analytics 원시 이벤트에서 계산한다. |
| **서버** | 기존 FCM Admin SDK·인증 설정은 유지한다. 앱의 Crashlytics·Analytics 보고를 위해 Python Firebase 워커를 추가하지 않는다. 서버 로그·자원 지표는 5절의 별도 수집 경로로 기록한다. |

기본 집계는 **일 단위 BigQuery 내보내기**를 사용한다. 실시간 내보내기는 필수 범위에서 제외하며, 도입 시 지원 요금제와 비용을 따로 확인한다. Firebase Performance Monitoring도 필수 의존성으로 두지 않고, API 시간과 화면 표시 시간은 앱에서 직접 측정한다.

참고: [Crashlytics 설정](https://firebase.google.com/docs/crashlytics/android/get-started) · [Analytics 설정](https://firebase.google.com/docs/analytics/android/get-started) · [Crashlytics·세션 내보내기](https://firebase.google.com/docs/crashlytics/bigquery-export) · [Firebase·Analytics 내보내기](https://firebase.google.com/docs/projects/bigquery-export)

## 3. 기능별 계측

각 흐름의 첫 사용자 동작을 사용 1회로 기록한다. 공통 결과는 `success`, `error`, `timeout`, `cancelled`로 구분하고, 원인은 `error_code` 또는 `reason`으로 기록한다. 서버 저장과 화면 반영은 각각 기록한다. 앱 종료 등으로 마지막 이벤트를 관측하지 못한 실행은 미완료로 표시하고, 취소·오류로 임의 변환하지 않는다.

| 기능 | 기록할 단계 | 상세 필드 |
|---|---|---|
| **음성 답장** | 녹음 시작 → STT 완료 → 초안 표시 → 답장 저장 | 마이크 권한 결과, 녹음 길이, 인식 시간, 초안 수정 여부, 재시도 횟수 |
| **가족 기억 검색·게시글 질문** | 질문 제출 → 큐 대기 → Graphiti 조회 → 답변 생성 → 화면 표시 | 음성·텍스트 입력 방식, 단계별 시간, 근거 수, 답변·결과 없음·근거 부족 구분, 모델·프롬프트 버전 |
| **사진 게시** | 게시 요청 → 업로드 완료 → 서버 저장 → 피드 반영 | 사진 수, 업로드 바이트, 업로드 시간, 재시도 횟수 |
| **기억 구축(construction)** | 게시글 저장 → 처리 대상 발견 → 설명 생성 → Graphiti 저장 완료 | 미처리 건수, 발견·처리 시작까지의 시간, 설명 생성·Graphiti 저장 시간, 시도 횟수, 실패 단계 |
| **글·요약 읽어주기** | 재생 요청 → 실제 재생 시작 → 완료·중단 | TTS 캐시 적중 여부, 재생 시작까지의 시간, 재생 길이, 종료 사유 |
| **오늘의 질문·푸시** | 질문 열기 → 답변 저장 / 푸시 큐 등록 → FCM 수락 → 알림 열기 → 목적 화면 도착 | 알림 유형, 큐 대기 시간, 발송 시도 횟수, 딥링크 처리 결과 |
| **첫 사용·피드** | 앱 시작 → 첫 피드 표시 / 가족방 참여 → 첫 게시 또는 답장 | 콜드 스타트 여부, 첫 피드 표시 시간, 참여 결과, 화면 모드 |

Construction과 푸시 발송은 시스템 처리량으로 별도 집계하고, 사용자 기능 사용 횟수에 더하지 않는다. **FCM 수락은 단말 수신·표시·열기 성공을 뜻하지 않는다.** `fcm_accepted`, `notification_opened`, `destination_shown`을 구분하고, 수신·표시 이벤트를 수집하지 않은 상태에서는 전달률·표시율을 계산하지 않는다.

## 4. 계층별 수집 및 ID 전달

| 계층 | 구현 |
|---|---|
| **Android 앱** | Crashlytics로 크래시·ANR을 수집하고, Firebase Analytics에 `feature_used`, `feature_stage`, `api_result`를 기록한다. `api_result`는 개별 HTTP 시도의 시작부터 응답 본문 수신 완료·실패·취소까지 측정한다. 결과 표시 시간은 사용자 동작부터 실제 화면 반영까지 별도로 측정한다. |
| **nginx** | 요청마다 `request_id`를 발급해 Django와 앱 응답에 전달한다. JSON 로그에 메서드·정규화한 경로, 최종 HTTP 상태, upstream 상태와 연결·헤더·응답 시간, 전체 요청 시간, 응답 크기를 기록한다. `503`은 **수동 점검·upstream 장애·Django 기능 오류**로 구분하며, 원래 upstream 상태와 실패 사유를 보존한다. |
| **Waitress·Django** | Django 미들웨어에서 경로 템플릿, HTTP 상태, 처리 시간, 오류 코드를 기록한다. nginx의 upstream 시간은 Waitress 대기 등을 포함할 수 있으므로 Django 처리 시간과 구분한다. Waitress의 태스크 큐 대기 경고와 서비스 시작·종료·재시작도 수집한다. |
| **검색·construction·푸시** | 작업별로 전달받은 ID와 `stage`, `duration_ms`, `result`, `attempt`를 기록한다. 검색은 큐·Graphiti·LLM 시간을, construction은 발견 지연·설명 생성·Graphiti 저장 시간을, 푸시는 큐 대기·FCM 호출 시간을 구분한다. |
| **음성 처리** | 현재 STT·TTS 호출 위치에서 요청별 소요 시간·결과·오류 코드와 TTS 캐시 적중 여부를 기록한다. 음성 계측을 위해 별도 프로세스를 신설하지 않는다. |

참고: [Analytics 이벤트](https://firebase.google.com/docs/analytics/android/events) · [nginx 액세스 로그](https://nginx.org/en/docs/http/ngx_http_log_module.html) · [nginx upstream 변수](https://nginx.org/en/docs/http/ngx_http_upstream_module.html#variables) · [Waitress 구조](https://docs.pylonsproject.org/projects/waitress/en/stable/design.html)

### 4.1. 이벤트와 공통 필드

| 이벤트 | 기록 시점·필수 내용 |
|---|---|
| `feature_used` | 첫 사용자 동작 시 `feature`, `operation_id`를 기록한다. 재시도 시 같은 기능 시작 이벤트를 추가하지 않는다. |
| `feature_stage` | 관측한 단계마다 `feature`, `operation_id`, `stage`, `result`, `attempt`, 해당 단계의 `duration_ms`를 기록한다. 마지막 단계에는 사용자 동작부터의 `elapsed_ms`도 기록한다. |
| `api_result` | 각 HTTP 시도가 끝나면 `operation_id`, 메서드·API 경로 템플릿, `attempt`, `duration_ms`, `result`, 응답의 `request_id`·HTTP 상태 또는 관측한 오류 코드를 기록한다. 응답이 없으면 응답 필드는 비워 둔다. |

모든 자체 계측 레코드는 `schema_version`, `event_id`, 발생 시각, `environment`를 포함하고, 앱 버전 또는 서버 배포 버전, `component`를 식별할 수 있어야 한다. `event_id`는 레코드 생성 시 한 번 발급하며 같은 레코드의 재전송에도 유지한다. `stage`, `result`, `error_code`, `reason`은 정해진 값만 허용한다. 요청·작업 레코드는 해당하는 경우 `operation_id`, `request_id`, `job_id`, `notification_id`를 포함하며, 서버 로그에는 서비스명·프로세스 ID·스레드명을 추가한다. nginx·systemd 원본 필드는 수집 시 공통 스키마에 맞춰 정규화한다.

### 4.2. ID 전달과 시간 기준

- **사용자 실행:** 앱이 `operation_id`를 UUID로 생성하고 관련 HTTP 요청의 `X-Operation-ID`로 전달한다. nginx에서 형식·길이를 검증하며, Django와 워커까지 같은 값을 전달한다. 같은 실행의 재시도는 ID를 유지하고 새 사용자 동작에는 새 ID를 발급한다.
- **HTTP 시도:** nginx가 `request_id`를 생성해 upstream 요청과 앱 응답의 `X-Request-ID`에 넣는다. 외부에서 보낸 `X-Request-ID`는 덮어쓴다. 오류·점검 응답에도 ID를 포함한다. 응답을 받지 못해도 요청이 nginx에 도달했다면 `operation_id`로 서버 기록을 조회할 수 있다.
- **비동기 작업:** construction은 게시글 저장 시, 푸시는 outbox 생성 시 원본 `operation_id`·`request_id`와 작업 ID를 DB에 보존하도록 보완한다. 폴링·스레드 전환·프로세스 재시작 뒤에도 전달하고, 작업 재시도는 같은 작업 ID를 사용한다. 검색 큐에는 ID를 명시적으로 넘겨 요청 스레드의 컨텍스트에만 의존하지 않는다.
- **서버 생성 작업·푸시 열기:** 예약 작업은 서버가 `operation_id`를 발급하고 사용자 기능 사용량에서 제외한다. 푸시를 여는 사용자 동작에는 새 `operation_id`를 발급하며 `notification_id`로 발송 기록과 연결한다. 기존 FCM payload의 `event_id`는 알림 ID이므로, 계측 시 `notification_id`로 기록해 텔레메트리의 `event_id`와 구분한다.
- **시간:** 발생 시각은 UTC로 저장하고 일별 집계·표시는 `Asia/Seoul`로 통일한다. 구간 소요 시간은 각 프로세스의 단조 시계로 측정해 `ms`로 기록한다. DB 저장부터 작업 시작까지의 대기 시간은 서버 시각으로 측정하며, 단말과 서버의 시각을 빼서 네트워크 시간을 계산하지 않는다.

## 5. 서비스 운영 및 서버 상태 수집

운영 프로세스의 실행·부팅 시 자동 시작·실패 시 재시작은 **systemd**가 담당한다. API 서버와 별도 워커는 독립 서비스로 등록하고, 서비스별 작업 디렉터리·Python 환경·환경 변수·로그 경로를 명시한다. 종료 코드·종료 신호와 재시작 횟수를 보존한다. [systemd 서비스 설정](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html)

| 구성 요소 | 실행·관리 기준 |
|---|---|
| **nginx** | 별도 서비스로 운영하고 설정 오류·upstream 연결 실패·타임아웃과 접근 로그를 수집한다. |
| **API** | Waitress가 `configs.wsgi:application`을 실행한다. bind 주소·포트는 nginx upstream과 일치시킨다. Waitress 요청 처리 스레드 수를 기록하고, 긴 AI 호출이 다른 API 요청을 지연시키는지 관측한다. |
| **검색 풀** | 현재의 Django 프로세스 내부 스레드 풀을 사용한다. 별도 검색 실행 명령을 만들지 않는다. `GRAPHITI_SEARCH_WORKERS` 설정값, 살아 있는 검색 스레드 수, 실행 중 건수와 대기 건수를 기록한다. |
| **Construction** | 기본은 WSGI에서 시작하는 `CONSTRUCTION_MANAGER`와 가족별 스레드다. 별도 프로세스로 운영하는 배포는 API 서비스에서 `GRAPHITI_AUTO_CONSTRUCTION=0`으로 설정하고 별도 서비스에서만 실행한다. 가족별 파일 락을 공유하되, 락에만 의존해 여러 supervisor를 상시 중복 실행하지 않는다. |
| **푸시** | 기존 `python backend/manage.py run_push_worker`를 API와 독립된 서비스로 계속 실행한다. 발송 루프 상태·시도·실패·재시작을 기록한다. |
| **기타 예약 작업** | `run_digest_scheduler` 등 실제 운영하는 예약 프로세스도 별도 서비스로 등록하고 시작·종료·실패·최근 성공 시각을 수집한다. |
| **대시보드** | 필요할 때 `python backend/manage.py run_telemetry_dashboard`를 수동 실행한다. API와 별도 프로세스에서 로컬 JSON 로그와 현재 자원을 읽는다. 별도 관측 플랫폼·수집 서비스는 설치하지 않는다. |

systemd는 별도 프로세스의 종료를 감지한다. API 내부 검색·construction 스레드의 건강 상태는 애플리케이션에서 별도로 관측한다. API를 재시작하면 내부 검색 풀·construction도 함께 재시작한다. 검색 큐는 현재 메모리 큐이므로 재시작 중 미완료 요청을 성공으로 처리하지 않고, 클라이언트 재시도는 같은 `operation_id`를 유지한다.

호스트 자원과 큐 상태는 대시보드 조회 시 수집하며, 기본 화면 갱신은 **5초 간격**이다. 프로세스 생존과 별도로 최근 폴링·작업 완료 시각, 현재 실행 중 작업의 경과 시간을 기록하며, 작업이 없는 상태와 처리가 멈춘 상태를 구분한다. 수집 누락은 0으로 표시하지 않고 `데이터 없음`으로 표시한다.

| 지표 | 집계 기준 |
|---|---|
| **호스트·서비스** | 호스트 CPU 사용률, 메모리 사용·가용량, 데이터·로그 디스크 사용률과 여유 공간, 서비스별 CPU·메모리 사용량·실행 상태·재시작 횟수 |
| **검색 큐** | 실행 중 작업을 제외한 대기 건수, 가장 오래 기다리는 작업의 대기 시간, 작업 시작 시점의 큐 대기 시간 |
| **Construction 미처리량** | 현재 처리 대상인 게시글 중 Graphiti 저장이 완료되지 않은 건수와 가장 오래된 항목의 저장 후 경과 시간. 폴링 기반 미처리량으로 정의하고 검색 메모리 큐와 구분한다. |
| **푸시 큐** | 발송 가능한 pending, 재시도 대기, sending, 최종 실패·취소·만료 건수를 구분한다. 최초 등록부터 첫 시도까지의 시간과 각 시도의 발송 가능 시각부터 실제 시작까지의 대기 시간을 기록한다. |

애플리케이션 구조화 로그는 stdout/stderr와 로컬 회전 JSONL 파일에 기록하고, 대시보드가 해당 파일과 nginx JSON 접근 로그를 직접 읽는다. 서버 로그·지표의 저장·조회 경로는 7절의 대시보드 구성을 따른다. 수집기 설정·저장 위치·서비스 실행 방법을 배포 문서에 명시한다. 앱 지표는 Firebase·BigQuery, 서버 지표는 서버 수집 경로를 사용한다.

## 6. 집계·로그 정책

- **대시보드:** 서버 지표와 로그는 7절의 웹 대시보드에서 함께 조회한다. 앱 버전별 ANR·크래시와 기능별 사용량·완료율은 Firebase·BigQuery 조회 화면으로 연결한다. 비율에는 분자·분모와 대상 기간을 함께 표시하고, 각 화면에 데이터 기준 시각과 수집·내보내기 지연을 표시한다.
- **ANR:** Crashlytics의 `firebase_session_id`와 Firebase sessions의 `session_id`를 같은 앱 기준으로 연결한다. 분모는 Android 11 이상이며 `crashlytics_data_collection_enabled=true`인 고유 세션 수, 분자는 그중 ANR이 1회 이상 보고된 고유 세션 수다. Google Analytics 세션은 이 분모로 사용하지 않는다. 늦게 수신한 보고는 해당 세션 날짜에 반영하고, 연결되지 않은 ANR은 별도 건수로 표시한다. 분모가 0이면 `데이터 없음`, 반올림 전 비율이 1% 이상이면 목표 미달로 판정한다. [ANR 수집 범위](https://firebase.google.com/docs/crashlytics/troubleshooting) · [BigQuery 데이터 스키마](https://firebase.google.com/docs/crashlytics/bigquery-dataset-schema)
- **사용량·완료율:** 같은 `event_id`의 중복 수신을 먼저 제거한다. 기능별 고유 시작 `operation_id`를 분모로 하고, 그 실행들 중 마지막 단계가 성공한 고유 ID 수를 분자로 한다. 시작일 기준으로 완료를 연결하고 미완료·늦은 완료를 구분한다. API 시도는 `api_result` 레코드 단위로 집계한다. 사용자 기능 사용량·시스템 작업량·알림별 단계 집계를 분리한다.
- **시간·오류율:** 각 계층·메서드·API 경로 템플릿·결과별 원시 `duration_ms`에서 p50·p95를 계산하고 집계 건수를 함께 표시한다. 일별 p95의 평균으로 기간 p95를 계산하지 않는다. nginx·Django 요청 수를 합산하지 않으며, 계층별 전체 요청 대비 4xx·5xx 비율을 나눠 표시한다. nginx의 499 등 클라이언트 연결 종료도 별도 표시하고, 상태를 받지 못한 앱 네트워크 실패를 HTTP 오류로 치환하지 않는다.
- **상세 로그:** 정상·실패 요청 모두 요약 레코드를 남긴다. 오류와 느린 요청의 단계별 로그는 전수 보관한다. 느린 요청 기준은 API·작업별 설정값으로 관리하고, 로그량이 늘면 정상 요청의 단계별 로그에만 샘플링을 적용한다. 사용량·비율·백분위 집계용 요약 이벤트에는 임의 샘플링을 적용하지 않는다. 보관 기간·용량 상한·파일 로테이션 또는 journald 정리 정책을 배포 설정에 명시한다.
- **데이터 보호·테스트 분리:** 수집 필드는 허용 목록으로 관리한다. 가족 글·댓글·검색어, 사진·음성·전사문, 프롬프트, 알림 제목·본문, 인증·FCM 토큰, 요청 본문·쿼리스트링은 수집하지 않는다. 예외 메시지·SDK 로그·URL에도 이 정보가 섞이지 않도록 제거하며, 스택 트레이스는 지역 변수·본문을 첨부하지 않는다. 자체 이벤트는 `environment`로 구분하고, 검수 빌드는 운영과 구분되는 패키지의 Firebase 앱으로 등록해 Crashlytics·Firebase sessions 데이터도 분리한다. 테스트 데이터는 운영 집계에서 제외한다.

## 7. 수동 실행 웹 대시보드 및 로컬 접속

운영자가 필요할 때 서버에서 Python 관리 명령 하나로 실행하는 **HTML/CSS/JavaScript 대시보드**를 제공한다. 현재 서버를 관찰하기 위한 도구로, 별도 관측 플랫폼·시계열 DB·로그 전송 에이전트·로그인 시스템은 필수 범위에서 제외한다. 로컬 브라우저에서 SSH 터널로 접속한다.

### 7.1. 실행·데이터 경로

- 서버에서 `python backend/manage.py run_telemetry_dashboard --port 8765`를 실행한다. 기본 바인딩은 `127.0.0.1`이며 Ctrl+C로 종료한다.
- 앱 서버와 워커는 개인정보를 제거한 JSONL 로그를 로컬 디렉터리에 기록한다. 프로세스별 파일을 회전해 크기를 제한한다. 대시보드는 최근 로그의 제한된 구간만 읽고, 조회 건수·잘림·파싱 실패를 표시한다. 장기 보관·재시작 후 완전한 이력 복구를 보장하지 않는다.
- nginx JSON 로그 경로도 설정할 수 있다. 요청량·오류율·p50·p95는 실제 읽은 로그에서 계층별로 계산한다. 호스트 CPU·메모리·디스크와 프로세스 상태, 검색 큐 스냅샷·DB의 작업 진행 상태를 함께 표시한다. 조회 실패·수집 전 상태는 `데이터 없음`으로 표시한다.
- Firebase·BigQuery는 기존 수집 경로를 유지하며 관련 콘솔 링크를 제공한다. 앱 ANR·사용량의 일 단위 집계와 서버의 현재 상태를 구분한다.

### 7.2. 화면과 조작

| 영역 | 표시·조작 |
|---|---|
| **헤더·필터** | 서버 이름, 한국 시간, 마지막 갱신 시각, 최근 15분·1시간·24시간, 서비스·계층·결과·API·ID 검색, 수동 갱신·자동 갱신 일시 정지 |
| **요약 카드** | 선택한 계층의 요청 수·오류율·p95와 현재 CPU·메모리·디스크. 0과 데이터 없음을 구분 |
| **트래픽·성능** | 시간대별 요청량·오류, API별 p50·p95·건수와 느린 API 순위 |
| **워커 상태** | 검색 대기·실행 중, construction 미처리·실패, 푸시 상태별 건수와 최근 진행 시각 |
| **로그 탐색** | 시각·서비스·단계·결과·시간·ID를 보여주는 표. 행 펼치기, 같은 ID로 좁혀 보기, 기본 최신 100건과 추가 조회 |

밝은·어두운 테마, 일관된 타이포그래피·여백·색상과 반응형 카드·차트를 사용한다. 정상·오류·미수집은 색상과 텍스트로 함께 구분한다. CSS·JavaScript·차트는 외부 CDN 없이 제공한다. 로그 문자열은 텍스트로 렌더링한다. 기본 5초 갱신과 일시 정지를 지원하며, 수집 지연·파일 없음·DB 조회 실패·결과 잘림을 화면에 표시한다.

### 7.3. SSH 접속

서버에서 대시보드를 실행한 상태로 **로컬 컴퓨터의 터미널**에서 아래 명령을 실행하고 [http://127.0.0.1:13000](http://127.0.0.1:13000)을 연다. `SSH_HOST_ALIAS`는 평소 사용하는 호스트 별칭 또는 `사용자명@서버주소`로 바꾼다.

```bash
ssh -N -T -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -L 127.0.0.1:13000:127.0.0.1:8765 SSH_HOST_ALIAS
```

대시보드는 루프백에서만 제공하며 공개 앱 nginx 경로로 노출하지 않는다. SSH의 기존 키·포트·점프 호스트 설정을 재사용한다. 터널이 끊기면 다시 실행한다. 서버 프로세스나 대시보드를 종료하면 실시간 관찰도 끝난다. README에는 설정·실행·로그 경로·접속·종료·문제 확인 방법을 적고, 상위 `CHEETSHEET.md`에는 명령만 간결하게 적는다. [OpenSSH 포트 포워딩](https://man.openbsd.org/ssh#L)

## 8. 검수 기준

1. 기존 Firebase 프로젝트에서 푸시가 동작하고, 별도 패키지의 검수 앱에서 Crashlytics 테스트 크래시·ANR과 Analytics 이벤트가 각각 수집된다. 크래시·ANR은 앱 재실행 후 보고를 확인한다. BigQuery에 Crashlytics·Firebase sessions·Analytics 내보내기가 구성되고, 실제 내보내기 이후 데이터 조회가 가능하다. 테스트 데이터는 운영 집계에서 제외된다.
2. 집계용 대상 세션 100개 중 1개 세션에서 ANR이 여러 번 발생해도 **ANR 세션 1/100 = `1.00%`로 표시되어 목표 미달**로 판정된다. Android 10 이하·수집 비활성 세션은 분모에서 제외한다. 늦은 보고·연결 실패·분모 0도 정책대로 처리한다.
3. 음성 답장 한 건에서 API를 두 번 재시도하면 **기능 사용 1회, API 시도 3회**로 집계된다. 동일 이벤트 재수신은 건수를 늘리지 않고, 새 사용자 실행은 별도 건수로 집계된다. 마이크 권한 거부와 STT 실패, 서버 저장 성공 후 화면 반영 실패를 구분할 수 있다.
4. 정상 요청, Django 기능 오류, 수동 점검, upstream 연결 실패·타임아웃을 재현한다. 앱·nginx·Django의 도달 여부와 원인을 ID로 조회하고, 응답을 받지 못한 시도도 `operation_id`로 조회한다. 검색 지연은 큐·Graphiti·LLM 단계로 나뉘어 표시된다.
5. 게시글 저장 뒤 지연되어 실행된 construction과 푸시 작업을 원본 요청에 연결할 수 있다. FCM 수락만 기록된 알림은 열기 성공으로 집계되지 않고, 실제 알림 열기·목적 화면 도착을 같은 `notification_id`로 연결한다.
6. 푸시 서비스의 비정상 종료 후 자동 재시작과 오류 로그를 확인한다. API 재시작 후 검색 풀·construction의 복구 또는 별도 construction 서비스의 정상 운영을 확인한다. 미완료 작업을 성공으로 집계하지 않으며, 가족별 construction 중복 실행이 방지된다. 대시보드에서 현재 자원·큐 지표와 관측된 서비스 상태를 조회할 수 있다.
7. 서버에서 대시보드를 수동 실행하고 로컬 컴퓨터에서 SSH 터널로 접속한다. 실제 로그·현재 지표와 갱신·필터·ID 검색·행 펼치기·테마 변경이 동작한다. 외부 CDN 없이 화면이 표시되고, 외부 인터페이스에 대시보드 포트가 열리지 않는다.
8. 차트·요약·표의 집계가 동일 필터의 원본 레코드와 일치한다. 계층별 요청을 중복 합산하지 않는다. 빈 데이터·조회 실패·로그 파싱 실패·잘림 상태를 구분하며, 개인정보와 HTML 실행 가능한 로그를 그대로 노출하지 않는다.
9. API를 중단해도 수동 실행 중인 대시보드는 읽을 수 있는 최근 로그를 표시한다. 종료·재실행과 로그 회전이 안전하게 처리되고, 장기 보관이나 별도 플랫폼 없이 README와 CHEETSHEET의 명령으로 사용할 수 있다.
