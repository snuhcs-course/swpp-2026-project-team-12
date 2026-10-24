# Android family memory search

Implemented on `feature/frontend-family-memories`, based on `iteration-2-demo`
commit `62c33e5c9bf9fbfd1fe7d449e64249472be61747`.

## Behavior

- Open **가족 추억 찾기** from the feed or the existing family room.
- Enter a question (up to 1,000 characters), or select one of the three examples.
- Submit the same authenticated `POST /api/searching/history/` request used by
  the web app. The only body field is `question`; the server determines the
  current family from the signed-in account.
- Show the returned `text` in an answer card. This is a single-question search,
  not a conversation with previous-question context.
- Prevent duplicate submissions, preserve the exact draft after a failed search,
  and offer sign-in after a 401 response.
- Cancel the client connection and ignore stale results when leaving the screen.
  Cancellation does not promise to stop work already running on the server.
- Restore the draft and completed answer after activity recreation, only for the
  same account, family and server. An interrupted search is not resubmitted
  automatically; the user can submit the preserved question again.
- Use the existing app colors and normal/large text modes. Search requests have
  a 150-second read timeout, matching the web app's search timeout setting.

No backend, database, web app, or prompt changes are included.

## Verification — 2026-10-24 KST

Environment: Android API 36, Medium_Phone ARM64 emulator, local mock HTTP server.
Production credentials and real family records were not used.

| Check | Result |
| --- | --- |
| Debug APK build | Passed |
| Debug lint | Passed; existing project warnings remain |
| Existing JVM tests (`FamilyTreeLayoutTest`) | 2 passed |
| New Android tests (`FamilyMemorySearchTest`) | 9 passed, 0 failed, 0 skipped |

Android test coverage:

1. Empty/whitespace validation, 1,000-character limit, example selection, both font sizes.
2. Authenticated family-wide POST payload and displayed answer; no comment/post-question submission.
3. Duplicate prevention, navigation while searching, and suppression of stale answers.
4. Server failure preserves the exact draft; retry succeeds.
5. Expired login provides a working sign-in action.
6. Empty, missing and malformed answer responses show a retryable error.
7. Recreation restores the answer and draft without repeating the request.
8. Family-room entry opens the search screen.
9. Recreation after an account change does not restore the previous account's question or answer.

The final APK was rechecked with all nine Android tests after the account/family/server
restoration guard was added. This does not establish production retrieval quality,
timeout behavior under a real 150-second delay, or full-app regression coverage.

## Reproduce

From the `client` directory, with the Android SDK and JDK configured:

```sh
./gradlew :app:assembleDebug :app:lintDebug :app:testDebugUnitTest \
  -PtalkDockApiUrl=https://talkdock.app/api/

./gradlew :app:connectedDebugAndroidTest \
  -Pandroid.testInstrumentationRunnerArguments.class=kr.talkdock.app.FamilyMemorySearchTest \
  -PtalkDockApiUrl=https://talkdock.app/api/
```

The tests temporarily use a local mock server and restore stored preferences.
Use a test emulator. Other instrumentation test classes were not run for this feature.

## Try with the deployed service

The supplied debug APK defaults to `https://talkdock.app/api/`. Sign in with an
existing account and open **가족 추억 찾기**. Existing debug server preferences
override the compiled default; if necessary, set **테스트 연결 설정** to
`https://talkdock.app/api/` and sign in again.

Real answers depend on the deployed search service and indexed family records.
