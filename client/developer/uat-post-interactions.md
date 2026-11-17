# UAT post interactions

This change is based on iteration-4-demo plus PRs #71 and #72. It leaves their family-tree and account behavior intact.

## Behavior

- Android restores the previous feed and reading position immediately when returning from the composer. A background request updates it. Snapshots are scoped to the server, account/session and family, and are cleared after publishing or switching families/accounts. A failed refresh keeps the cached feed available.
- Summary audio has a cancel/stop control below its text. Cancelling during summary or speech preparation prevents late playback. Inline controls and the assistant menu share playback state.
- Both the regular comment sheet and elderly detail screen keep the composer outside the scrolling history and above the keyboard. Failed sends retain the draft.
- Opening a voice reply waits for **말하기 시작**. The user stops recording, checks the reply and sends it explicitly. **다시 말하기** returns to the idle screen.
- Web dialogs follow the same comment/audio behavior and account for the visual viewport when the keyboard opens. Closing the web composer already preserves the underlying feed.

The existing tutorial close control is retained. The reported photo-upload failure (UAT 2-1) is deferred; this PR does not change upload processing, the AI prompts or the backend.

## Offline checks

No API keys or paid services are required. Android tests use a local mock server; browser tests intercept API calls with synthetic posts and comments.

```sh
cd client
./gradlew :app:testDebugUnitTest :app:lintDebug :app:assembleDebug :app:assembleDebugAndroidTest
adb shell settings put secure show_ime_with_hard_keyboard 1
./gradlew :app:connectedDebugAndroidTest \
  -Pandroid.testInstrumentationRunnerArguments.class=kr.talkdock.app.UatPostInteractionsTest,kr.talkdock.app.ErrorRecoveryTest,kr.talkdock.app.InlinePostAudioTest,kr.talkdock.app.FeedRefreshTest,kr.talkdock.app.UatAccountFeedbackTest,kr.talkdock.app.ReviewRoomUiTest,kr.talkdock.app.CommentComposerTest
```

With Playwright installed and its Chromium browser available, from the repository root:

```sh
node --test web/test_*.mjs
node web/developer/test-uat-post-browser.mjs
node web/developer/test-ui-modes-browser.mjs
node web/developer/test-uat-account-browser.mjs
```

`PLAYWRIGHT_MODULE` can point to an existing Playwright module; `PLAYWRIGHT_CHANNEL=chrome` uses installed Chrome. `UAT_QA_DIR` sets the output directory for UAT screenshots. Android screenshots are written to the test app's cache directory. Use `-PtalkDockDemo=true` consistently for all Android commands if testing an isolated demo package.

Physical-device checks still needed before release: Samsung keyboard/font settings, real microphone recognition and live speech playback. Mocked tests verify controls and request sequencing, not external service quality.
