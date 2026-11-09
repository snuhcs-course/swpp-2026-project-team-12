# Server availability notices

Frontend-only follow-up on `fix/frontend-ui`.

## Behavior

- API requests that receive a 5xx response without a useful JSON `error` show:
  `서버를 점검 중이거나 일시적인 문제가 생겼어요. 잠시 후 다시 이용해 주세요.`
  This also handles reverse-proxy HTML pages and empty 502/503/504 responses.
- Connection failures and timeouts have separate Korean notices. A connection failure cannot establish whether the server is undergoing maintenance or the device is offline.
- Useful JSON error messages and HTTP status codes are preserved, including validation errors, authentication expiry, and feature-specific availability errors.
- A failed startup room check keeps the saved login and provides **다시 연결하기**. It reruns startup checks; it does not bypass family membership verification.
- The feed retains its existing **다시 불러오기** action. Failed pull-to-refresh keeps the already displayed feed.
- Family memory search keeps the exact question draft and enables manual retry after failure.
- Upload, speech and image API transport failures use the same notice policy. Existing photo placeholders and inline audio error presentation remain in use.
- No automatic resubmission, polling, maintenance timetable, backend endpoint or server configuration was added. Navigation cancellation and missing local files are not presented as server outages.

## Validation — 2026-10-25 KST

Environment: Android API 36 emulator and loopback HTTP servers. No production account, live family records or AI calls were used.

| Check | Result |
| --- | --- |
| Debug build and lint | Passed |
| `ApiAvailabilityTest` | 11 JVM tests passed |
| `ServerAvailabilityTest` | 3 Android tests passed; feed checked with both font sizes |
| `FamilyMemorySearchTest` | 9 Android tests passed |
| `FeedRefreshTest` | 1 Android test passed |

The Android checks cover maintenance notices, preservation of login/question/feed state, and successful manual recovery when the mock service becomes available. They are not a full-app regression or a production maintenance drill.

## Reproduce

From `client/`, with the configured JDK, Android SDK and a test emulator:

```sh
./gradlew :app:testDebugUnitTest --tests kr.talkdock.app.data.ApiAvailabilityTest \
  :app:assembleDebug :app:lintDebug :app:assembleDebugAndroidTest \
  -PtalkDockApiUrl=https://talkdock.app/api/

adb install -r app/build/outputs/apk/debug/app-debug.apk
adb install -r app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk
adb shell am instrument -w -e class \
  kr.talkdock.app.ServerAvailabilityTest,kr.talkdock.app.FamilyMemorySearchTest,kr.talkdock.app.FeedRefreshTest \
  kr.talkdock.app.test/androidx.test.runner.AndroidJUnitRunner
```

The UI harness temporarily configures a mock account/server and restores saved preferences afterward.
