# Standard and elderly screen modes

This branch is based on `iteration-4-demo` at `0f0b17107de641159cfa170df0dc78607ba94f62`.
Its base file tree is identical to the previously tested Iteration 3 base (`7a8df58fbd919074bafbc90d8e82cf48afcdc33c`); only the integration history changed.
It implements the selected **More** standard layout and the elderly layout on Android and web.
There are no backend, API schema, database, launcher artwork, or APK changes in the PR.

## Behavior

| Area | Standard | Elderly |
| --- | --- | --- |
| Navigation | News / Day / Memories | One bottom **Write news** action; Day and Memories are in the assistant |
| News | Vertical feed; captions show at most two rendered lines before More; no search/family filters | Full captions and inline family comments |
| Post actions | Icons only for comments, voice comment, and listen; accessible names retained | Large comment and listen buttons with text |
| Comments | Bottom sheet with text/voice composer | Post detail with text/voice composer; Back restores the reading position |
| Assistant | Context follows the visible post | Docked to the right with the same icon and a “토닥 도우미” caption; includes Help |
| Day | Large calendar, selected-day thumbnails, story and audio actions | Same view, opened from the assistant |

Settings retain the existing account/family controls and add explicit screen choices, family-room switching, and account switching.
Signup can select the elderly screen. The choice is saved per account **on the current client**; it is not synchronized between devices or between Android and web.

First use of the elderly screen opens six-step practice. Help reopens it later. Practice uses a separate virtual post even when the real family has posts; it does not publish posts/comments, record the microphone, or call AI/speech services. Leaving practice preserves the real reading position.

Existing photo loading, voice recording, speech, today-question answers/results, family memory search, and server authorization are reused.
Inline comments load when their posts enter the viewport, with at most two concurrent requests and an explicit retry on failure.

## Files

- Android: `MainActivity.kt`, `FeedPostCard.kt`, `GuidedHelpView.kt`, assistant/calendar UI components, and associated instrumentation tests.
- Web: `app.js`, `floating-assistant.js`, `ui-modes.js`, `ui-modes.css`, `guided-help.js`, `index.html`, and tests.
- `PhotoLetterDeck` remains in use for memory evidence; it has not been removed.

## Reproduce checks

Initial screen-mode validation on 2026-11-09 used local synthetic data. The table below records that initial implementation; the compact-feed follow-up results are listed after it. These are targeted checks, not a claim that every repository test or production service was exercised.

| Check | Result |
| --- | --- |
| Android debug app/test builds and Lint | Pass |
| Android JVM unit tests | 39 passed |
| Screen modes / signup & account / refresh / composer / posting feedback | 6 / 5 / 1 / 9 / 2 passed |
| Floating assistant / today questions / family memory search | 7 / 13 / 17 passed |
| Additional photo-memory, stale-audio, and feed-order regressions | 3 passed |
| Total targeted Android instrumentation tests | 63 passed |
| Web Node tests | 59 passed |
| Web browser scenarios | 19 checks passed; no page runtime errors |

Compact-feed follow-up: debug app/test builds and Lint passed, 39 JVM tests passed, all 7 `ScreenModesTest` cases passed, 59 web Node tests passed, and 23 browser checks passed. This includes rendered two-line overflow (including short text with three explicit lines), icon-only standard actions, removed filters, expansion, and unchanged elderly controls.

Android requires JDK 17+, SDK 36, and an isolated API 36 emulator. From `client`:

```sh
./gradlew :app:assembleDebug :app:assembleDebugAndroidTest :app:testDebugUnitTest :app:lintDebug
```

Install the generated app and test APKs on the **test device**, then run the targeted UI suites. `ANDROID_SERIAL` must identify the test device, not a phone containing personal app data.

```sh
adb install -r app/build/outputs/apk/debug/app-debug.apk
adb install -r app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk
adb shell am instrument -w \
  -e class kr.talkdock.app.ScreenModesTest,kr.talkdock.app.AccountScreensTest,kr.talkdock.app.FeedRefreshTest,kr.talkdock.app.PostComposerTest,kr.talkdock.app.PostingFeedbackTest,kr.talkdock.app.FloatingAssistantTest,kr.talkdock.app.DailyQuestionTest,kr.talkdock.app.FamilyMemorySearchTest \
  kr.talkdock.app.test/androidx.test.runner.AndroidJUnitRunner
```

Read the instrumentation summary: the process exit code alone does not establish that all tests passed.
These tests use local mock servers and synthetic accounts/family data.
The three additional checks are `ReviewPhotoMemoryTest`, `InlinePostAudioTest#leavingPendingTextSummaryDoesNotRenderOnAnotherPage`, and `PostQuestionUiTest#feedIsNewestFirstWithTimezonesAndTimestampTiesInBothSizes`; pass these as the instrumentation `class` argument to repeat them.

From the repository root:

```sh
node --test web/test_*.mjs
node web/developer/test-ui-modes-browser.mjs
```

The browser check requires Playwright and its Chromium browser. `PLAYWRIGHT_MODULE` can point to an existing Playwright module; `PLAYWRIGHT_CHANNEL=chrome` uses an installed Chrome.
It intercepts API requests locally and writes screenshots/results to ignored `web/.qa/ui-modes/`.
Production login, real AI quality, microphone hardware, and physical-device accessibility are outside these mock checks.

## PR 67 CI follow-up

[CI run 98](https://github.com/snuhcs-course/swpp-2026-project-team-12/actions/runs/42599750379) on `b9d1f0b` passed backend/web integration, web modules, and Android unit/test builds. The Android emulator job failed.

- Migrated remaining horizontal-letter, old profile menu, and old question/voice button expectations to the vertical feed, settings gear, assistant dialog, and icon actions. Tests continue to check source-post IDs, photo access, voice cancellation, and stale-answer isolation.
- Added the calendar-history response to the local digest/audio fixtures and made the shared test helper navigate through the calendar/story views.
- Isolated first-use preferences for each test; mock-server port reuse must not suppress the tutorial in a later test.
- Compared recreated text layout relative to its card, while retaining absolute drag checks. Selected-post fixtures reserve a viewport of space so each post can be centered on both large and small devices.
- Kept family-memory menu selection in one UI turn to avoid a photo-layout callback dismissing it between test calls.
- Fixed a production issue: the assistant now offers **Stop listening** for the currently playing feed post, as well as for a playing detail post.
- Ran `web/test_ui_modes.mjs` locally alongside the existing web tests. The CI workflow remains unchanged so the push does not require a token with workflow-edit permissions. No existing CI tests were excluded and no new skips were introduced.

Local verification uses an API 36 emulator with hardware configured at 320×640 / density 160. A `wm`-only override retains a different physical touch density and is unsuitable for the pinch test; the family-tree test and production tree code remain unchanged. `ApiRoundTripTest` uses the unchanged Django API with a temporary SQLite database and media directory, served through a standalone WSGI application without starting Graphiti. The GitHub emulator is API 34; its result still needs a new CI run after the fix is pushed. Live Graphiti remains opt-in.

Final local run on 2026-11-09: **122 instrumentation cases discovered, 121 passed, 1 existing live-Graphiti assumption skip, 0 failures** (288.754 seconds). This was a fresh complete run after the fixes, not just the targeted failures. Android builds, 39 JVM tests, and Lint passed; the local web command, including `web/test_ui_modes.mjs`, passed all 59 tests. Backend source files were not changed.

Full local instrumentation command (test API server must already be running):

```sh
adb shell am instrument -w -e server http://10.0.2.2:18067/api/ \
  kr.talkdock.app.test/androidx.test.runner.AndroidJUnitRunner
```

To update the existing PR after reviewing the local changes:

```sh
git add .github/workflows/ci.yml client/app/src client/developer/frontend-screen-modes.md
git commit -m "fix: align screen-mode tests and assistant playback"
git push
```

This updates PR #67 on the same branch; a new PR is not needed.

## Assistant appearance follow-up

The elderly assistant now docks on the **right**, uses the standard screen's icon appearance, and shows **토닥 도우미** underneath. The caption stays upright when the Android artwork is mirrored and is reserved within the viewport so it does not cover bottom navigation. The web tutorial uses the same round launcher styling and right-side placement.

Verified after this appearance change: Android builds/Lint and 39 JVM tests passed; all 14 screen-mode and floating-assistant instrumentation cases passed on the small API 36 emulator. All 59 web Node tests and 27 browser checks passed, including matching standard/elderly icon styling, right docking, the visible caption, its clearance above navigation, and tutorial replay. No workflow or backend files changed.

## Suggested PR

**Title:** `feature: add standard and elderly screen modes for Android and web`

**Description:**

```md
## Changes
- Replace the news carousel with a vertical feed and a compact today-question banner.
- Add the selected standard layout with expandable captions, comment sheets, and News / Day / Memories navigation.
- Keep the standard feed free of search/family filters, show icon-only post actions, and collapse captions after two rendered lines.
- Add an elderly layout with full captions, inline comments, large actions, one bottom compose button, and a right-docked assistant using the standard icon with a “토닥 도우미” caption.
- Add calendar-based day previews and a story view with photos above the summary.
- Add per-account client screen preferences and six-step, replayable practice using a separate virtual post.
- Preserve the reading position when returning from comments and keep existing memory, voice, and question flows.

## Validation
- Android debug builds and Lint passed; 39 JVM unit tests and 63 targeted instrumentation tests passed on an API 36 emulator.
- Web: 59 Node tests and 19 browser checks passed, with no page runtime errors.
- Compact-feed follow-up: builds/Lint, 39 JVM tests, 7 Android screen-mode cases, 59 web Node tests, and 23 browser checks passed.
Local mock data is used; live AI, production accounts, and physical microphone/device behavior were not tested.
```

## Publish manually

No commit, push, or PR is created automatically. Run these commands in this branch's worktree:

```sh
git status --short
git add client/app/src/main/java client/app/src/androidTest client/developer/frontend-screen-modes.md web
git diff --cached --stat
git commit -m "feature: add standard and elderly screen modes"
git push -u origin feature/frontend-screen-modes
```


Open the PR with **base: `iteration-4-demo`**, **compare: `feature/frontend-screen-modes`**.
If the team's integration branch has changed, agree on that destination before opening the PR.
