# Telemetry 운영·검수

명세는 [telemetry.md](telemetry.md)를 따른다. 대시보드는 Python 관리 명령과 정적 HTML/CSS/JavaScript만 사용한다. 외부 관측 플랫폼·컨테이너·CDN 설치가 필요 없다.

## 적용

저장소 루트에서 기존 Python 환경을 활성화하고 마이그레이션한 뒤 API·워커를 재시작한다. 실행 중인 기존 프로세스는 재시작 전까지 새 계측을 사용하지 않는다.

```bash
python -m pip install -r backend/requirements.txt
python backend/manage.py migrate
TELEMETRY_ENVIRONMENT=production bash deploy/run-service.sh api
# 별도 터미널
TELEMETRY_ENVIRONMENT=production bash deploy/run-service.sh push
```

API는 `127.0.0.1:8002`, 배포용 nginx는 `127.0.0.1:8080`을 사용한다. API 바인딩을 바꾸면 nginx `proxy_pass`도 맞춘다. 개발용 `manage.py runserver`에서도 요청 계측은 동작한다. 기존 Firebase Admin 인증과 AI·Neo4j 설정을 그대로 사용한다. 로그에는 원문·검색어·전사문·알림 내용·토큰을 넣지 않는다. 외부 라이브러리 오류는 예외 유형과 코드 위치만 남긴다.

```bash
mkdir -p deploy/nginx/run
nginx -t -p "$PWD/deploy/nginx/" -c nginx.conf
nginx -p "$PWD/deploy/nginx/" -c nginx.conf
# 이미 해당 prefix의 nginx가 실행 중이면 시작 대신 reload
nginx -p "$PWD/deploy/nginx/" -c nginx.conf -s reload
```

현재 운영 nginx 설정이 저장소 예제와 다르면 `map`·`log_format telemetry`·`access_log`와 요청 ID 관련 설정을 운영 파일에 옮긴 후 `nginx -t`로 확인한다. 요청 ID는 nginx가 발급해 앱 응답과 Django에 동일하게 전달한다. 쿼리를 포함하는 nginx 기본 error 로그는 대시보드에서 읽지 않으며 예제의 error 로그는 `crit` 수준으로 제한한다. 원인 분류는 안전한 JSON 접근 로그의 `upstream_status`·`reason`으로 확인한다.

## 대시보드: 서버

API와 같은 저장소·환경·DB·로그 경로에서 실행한다. 대시보드는 검색 풀·Graphiti를 시작하지 않는다.

```bash
python backend/manage.py run_telemetry_dashboard --port 8765 \
  --nginx-log "$PWD/deploy/nginx/run/access.log"
```

기본 로그 경로는 `.local/telemetry/`이고, `TELEMETRY_LOG_DIR`로 변경할 수 있다. API·워커·대시보드에 같은 값을 사용한다. `TELEMETRY_STATE_DIR`도 변경했다면 동일하게 전달한다. 대시보드 프로세스의 CPU·메모리는 관측 대상 서비스에 포함하지 않는다.

## 대시보드: 내 컴퓨터

```bash
ssh -N -T -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
  -L 127.0.0.1:13000:127.0.0.1:8765 SSH_HOST_ALIAS
```

브라우저에서 `http://127.0.0.1:13000`을 연다. `SSH_HOST_ALIAS`는 평소의 SSH 호스트 별칭 또는 `사용자명@서버주소`다. 키·점프 호스트·SSH 포트 설정을 재사용한다. 로컬 13000 포트가 사용 중이면 터널 명령의 첫 포트와 브라우저 주소를 함께 바꾼다. 서버는 루프백에만 바인딩하며 SSH 계정으로 접근한다. 대시보드에 별도 로그인이나 공개 nginx 경로는 없다.

상단의 기간·HTTP 계층·서비스·구성 요소·결과·API 필터를 선택한다. 요약·그래프·API 순위는 같은 필터를 사용한다. HTTP 합계는 Django와 nginx 중 선택한 계층만 센다. ID 검색으로 한 실행의 관련 로그를 모으고, 행을 눌러 상세 필드를 확인한다. 워커·자원은 기간 집계와 구분되는 현재 값이다. 5초 갱신을 멈추거나 수동 새로고침할 수 있다. 밝은·어두운 테마를 지원한다.

대시보드 터미널과 SSH 터미널에서 각각 Ctrl+C로 종료한다. API·워커는 계속 동작한다. API가 중단되어도 별도로 실행 중인 대시보드에서 읽을 수 있는 로그는 조회할 수 있다.

## 로그·데이터 한도

각 Python 프로세스는 PID별 JSONL 파일을 최대 5 MiB씩 현재 파일과 백업 두 개로 회전한다. 대시보드는 최신 32개 파일에서 각각 마지막 1 MiB만 읽고, 중복 이벤트를 제거한 최신 10,000건을 집계한다. 표는 기본 100건, 추가 조회는 최대 1,000건이다. 잘림이 표시되면 **현재 읽은 구간의 집계**이며 전체 기간의 완전한 통계가 아니다. 장기 보관 서비스는 없다. 종료된 과거 PID의 로그 파일은 필요할 때 정리한다. 실행 중인 프로세스의 파일은 지우지 않는다.

CPU는 첫 조회와 다음 조회 사이의 사용률이므로 첫 화면에는 `—`가 표시된다. 메모리·디스크는 호스트 현재 값이다. 프로세스 CPU는 한 코어를 100%로 표현하므로 여러 코어를 사용하면 100%를 넘을 수 있다. 실행 중인 작업의 상세 상태는 DB, 검색 풀은 프로세스가 쓰는 로컬 스냅샷에서 읽는다. 검색 작업이 없고 스냅샷을 아직 쓰지 않았다면 `미관측`이다. 큐 상태는 API 재시작 시 사라지는 검색 메모리 큐와 DB에 남는 작업 이력을 구분한다.

`데이터 없음`은 계측 시작 전이거나 조건에 맞는 로그가 없는 경우다. DB 오류가 뜨면 `migrate`, `DJANGO_DB_PATH`, 실행 사용자를 확인한다. 파일이 안 보이면 `TELEMETRY_LOG_DIR`, 읽기 권한, API·워커 재시작 여부를 확인한다. nginx 로그가 없으면 `--nginx-log` 경로와 JSON 로그 설정을 확인한다. SSH 연결 실패는 포트 중복·서버 명령 실행 여부·SSH TCP 포워딩 허용을 확인한다.

## 서비스 운영 선택

수동 실행은 `deploy/run-service.sh api|push|construction|digest`를 사용한다. 자동 시작·실패 시 재시작이 필요하면 `deploy/systemd/talkdock@.service.example`의 사용자·절대 경로를 실제 환경에 맞춰 `/etc/systemd/system/talkdock@.service`로 설치한 뒤 선택한 인스턴스만 활성화한다.

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now talkdock@api talkdock@push
sudo systemctl status talkdock@api talkdock@push
journalctl -u talkdock@api -u talkdock@push --since '10 minutes ago'
```

기본 construction은 API 내부에서 실행한다. 별도 `construction` 서비스를 쓰려면 `.env`의 `GRAPHITI_AUTO_CONSTRUCTION=0`으로 바꾼 뒤 API를 재시작한다. `run_construction_supervisor` 명령은 해당 프로세스에서만 자동 관리를 활성화한다. 가족별 수동 `run_construction_worker --family-id ID`도 기존처럼 사용할 수 있다. 여러 supervisor를 겹쳐 실행하지 않는다. 대시보드는 수동 실행한다.

## Firebase 설정과 실제 기기 검수

앱에는 호환되는 Firebase BoM과 Crashlytics·Analytics·Messaging SDK가 포함된다. `google-services.json`이 없으면 로컬 개발·CI 빌드는 계속 가능하며 Firebase 보고는 동작하지 않는다. 기존 서버 ADC로 설정을 복구하려면 아래 명령을 사용할 수 있다. `--register-test-app`은 검수 앱이 없을 때만 기존 프로젝트에 등록하며, 운영 앱을 새로 만들지 않는다. 설정 파일은 Git에서 제외된다.

```bash
python backend/manage.py configure_firebase_telemetry --register-test-app
```

기존 프로젝트에서 Google Analytics를 활성화하고 운영 패키지 `kr.talkdock.app`의 설정을 설치한다. 검수용은 별도 패키지 `kr.talkdock.app.memorydemo`로 등록하고 해당 설정 파일을 사용한다. debug 기본 패키지는 수집을 비활성화하고, `.memorydemo` debug만 `environment=test`로 수집한다. release는 `production`이다. 계정 토큰이나 개인정보를 Analytics user ID로 설정하지 않는다.

```bash
cd client
./gradlew :app:assembleDebug -PtalkDockDemo=true
adb install -r app/build/outputs/apk/debug/app-debug.apk
adb shell am start -n kr.talkdock.app.memorydemo/kr.talkdock.app.TelemetryCheckActivity --ez enable true
adb shell setprop debug.firebase.analytics.app kr.talkdock.app.memorydemo
```

검수 화면에서 테스트 이벤트·크래시·ANR을 명시적으로 실행한다. ANR 버튼은 메인 스레드를 20초 멈춘다. 필요하면 멈춘 동안 화면을 한 번 더 터치해 Android 입력 응답 감지를 유발한다. 크래시·ANR 뒤 앱을 재실행하고 Firebase 콘솔 보고를 확인한다. ANR은 Android 11 이상에서 확인한다. 이 Activity는 debug APK에만 포함되며 `.memorydemo`와 `--ez enable true` 둘 다 있어야 열린다. 자동 CI에서 크래시나 ANR을 발생시키지 않는다.

Firebase 프로젝트 설정 → 통합 → BigQuery에서 Crashlytics 내보내기·**Include sessions**·Analytics 내보내기를 각각 활성화한다. 운영·검수 앱을 분리하고 일별 내보내기가 도착한 뒤 `deploy/telemetry/sql/`의 `PROJECT_ID`, 앱 테이블 이름, Analytics 속성 ID를 실제 값으로 바꿔 실행한다. `anr.sql`은 한국 시간 직전 7개 완료 날짜의 수집 활성 Android 11+ 고유 세션을 분모로 사용한다. ANR 중복은 세션 단위로 제거하며 1/100은 1.00%로 목표 미달이다. 연결되지 않은 ANR 건수도 반환한다. `feature_usage.sql`은 이벤트 중복 제거와 기능별 마지막 성공 단계, `api_latency.sql`은 시도별 p50·p95를 계산한다. 늦은 보고가 있으면 최근 기간을 다시 집계한다. 실제 Firebase 보고·BigQuery 쿼리 실행은 해당 프로젝트 접근 권한과 실제 기기 검수가 필요하다.

## 테스트

```bash
MOCK_AI_TESTS=1 LIVE_GRAPHITI_TESTS=0 OPENAI_API_KEY= ELEVENLABS_API_KEY= python -m pytest
python backend/manage.py makemigrations --check --dry-run
# 선택적 실제 브라우저 검사
python -m pip install playwright
python -m playwright install chromium
python backend/developer/check_telemetry_browser.py
# Android
cd client
./gradlew :app:testDebugUnitTest :app:lintDebug :app:assembleDebugAndroidTest :app:assembleApks
```

Python 테스트는 실제 임시 nginx 프록시의 정상·기능 오류·점검·upstream 장애, ID 전달·개인정보 제외, 작업 재시도와 대시보드 HTTP·집계를 검사한다. nginx가 없으면 해당 통합 검사는 건너뛰며 CI는 nginx를 설치한다. 브라우저 검사는 페이지 추가·상세·ID 필터·빠른 초기화·테마·모바일 레이아웃을 실제 Chromium으로 검증한다. Android 단위 테스트는 실제 로컬 HTTP 서버로 실행 ID 유지·시도 3회·오류 분류·개인정보 제외를 검사한다. 기존 에뮬레이터 CI는 화면 통합 검사를 계속 수행한다.

현재 서버에서 기존 ADC로 운영 설정을 복구했고 `kr.talkdock.app.memorydemo` 검수 앱을 같은 Firebase 프로젝트에 등록했다. Analytics 연결 정보 조회는 현재 서비스 계정에서 HTTP 403으로 거절되어, Analytics 연결 상태는 콘솔 권한으로 확인해야 한다. `firebase_crashlytics` BigQuery 데이터셋 조회는 HTTP 404로 반환되어 내보내기 설정도 아직 필요하다. 앱·SQL 구현과 로컬 테스트는 이 콘솔 설정과 독립적으로 제공한다.
