# UAT post interactions

This change is based on iteration-4-demo plus PRs #71 and #72. It leaves their family-tree and account behavior intact.

## Behavior

- Android restores the previous feed and reading position immediately when returning from the composer. A background request updates it. Snapshots are scoped to the server, account/session and family, and are cleared after publishing or switching families/accounts. A failed refresh keeps the cached feed available.
- Summary audio has a cancel/stop control below its text. Cancelling during summary or speech preparation prevents late playback. Inline controls and the assistant menu share playback state.
- Both the regular comment sheet and elderly detail screen keep the composer outside the scrolling history and above the keyboard. Failed sends retain the draft. On the elderly feed, **댓글 달기** opens the same composer inside the card instead of a separate screen; the detail screen opens by tapping the post (the photo on the web).
- Opening a voice reply waits for **말하기 시작**. The user stops recording, checks the reply and sends it explicitly. **다시 말하기** returns to the idle screen.
- Web dialogs follow the same comment/audio behavior and account for the visual viewport when the keyboard opens. Closing the web composer already preserves the underlying feed.

## Elderly screen follow-up

UAT feedback said the elderly screen needed too many nested taps and the assistant menu had too many items. The elderly screen no longer has the floating assistant:

- Bottom tabs are **소식 / 오늘 하루 / 가족 추억**. **가족에게 소식 남기기** sits at the top of the feed and **도움말** in the header.
- **소식 듣기** plays the summary at once; if no summary is available it reads the caption. The spoken text ends with a rule-based "(관계)의 소식에 답장해 보시는 건 어떨까요?" for other members' posts (not shown on screen).
- After listening, the card shows "이 소식 관련해서 궁금한 점을 토닥이에게 물어보세요!" with **소식 물어보기**, which opens the post question sheet.
- **댓글 달기** opens an in-card reply. A voice reply is shown for confirmation before **보내기**. Listening closes an open reply and opening a reply closes the summary; only one card has a reply open.
- **오늘 하루** shows one day with **◀ 전날**, a listen button and **글로 읽기**.
- **가족 추억** offers three examples personalized to the family, **말로 물어보기** (voice question) and **답변 듣기**.
- The first guide on the feed is 소식 듣기 → 댓글 달기 → 소식 물어보기 → 소식 쓰기. 오늘 하루 and 가족 추억 run a short hands-on finger tour on the first visit. **도움말** replays the guide for the current tab. Bundled fallback clips for these lines (`guide_elder_*.mp3`) were made with the ElevenLabs default voice.
- On Android the guide still works on the real feed, so a reply or post written during it is delivered to the family.

### Elderly UAT scenarios to re-run

| # | Scenario | Expected |
| --- | --- | --- |
| E1 | First login on the elderly screen | Guide points to 소식 듣기, then 댓글 달기, 소식 물어보기 and 가족에게 소식 남기기 in that order |
| E2 | 소식 듣기 on another member's post | Summary plays without another tap and ends with the reply suggestion; the question hint and **소식 물어보기** appear |
| E3 | 소식 듣기 on a post whose summary failed | The caption is read instead of an error |
| E4 | 댓글 달기 → 말하기 시작 → stop | The spoken text is shown; nothing is sent until **보내기** |
| E5 | 댓글 달기 → type → 보내기 | The comment appears in the card without leaving the feed |
| E6 | With a reply open, tap 소식 듣기 (same or other card) | The reply closes and audio starts |
| E7 | 소식 물어보기 | The question sheet opens for that post |
| E8 | First visit to 오늘 하루 / 가족 추억 | A finger tour points to the main buttons; **도움말** on that tab replays it |
| E9 | 가족 추억: an example, then 말로 물어보기 | Both search; **답변 듣기** reads the answer |
| E10 | Look for the assistant | No floating assistant on the elderly feed, detail, day or memory screens |

The existing tutorial close control is retained. The reported photo-upload failure (UAT 2-1) is deferred; this PR does not change upload processing, the AI prompts or the backend.

## Offline checks

No API keys or paid services are required. Android tests use a local mock server; browser tests intercept API calls with synthetic posts and comments.

```sh
cd client
./gradlew :app:testDebugUnitTest :app:lintDebug :app:assembleDebug :app:assembleDebugAndroidTest
adb shell settings put secure show_ime_with_hard_keyboard 1
./gradlew :app:connectedDebugAndroidTest \
  -Pandroid.testInstrumentationRunnerArguments.class=kr.talkdock.app.UatPostInteractionsTest,kr.talkdock.app.ElderInlineReplyTest,kr.talkdock.app.ScreenModesTest,kr.talkdock.app.FamilyMemorySearchTest,kr.talkdock.app.ErrorRecoveryTest,kr.talkdock.app.InlinePostAudioTest,kr.talkdock.app.FeedRefreshTest,kr.talkdock.app.UatAccountFeedbackTest,kr.talkdock.app.ReviewRoomUiTest,kr.talkdock.app.CommentComposerTest
```

With Playwright installed and its Chromium browser available, from the repository root:

```sh
node --test web/test_*.mjs
node web/developer/test-uat-post-browser.mjs
node web/developer/test-ui-modes-browser.mjs
node web/developer/test-uat-account-browser.mjs
```

`PLAYWRIGHT_MODULE` can point to an existing Playwright module; `PLAYWRIGHT_CHANNEL=chrome` uses installed Chrome. `UAT_QA_DIR` sets the output directory for UAT screenshots. Android screenshots are written to the test app's cache directory. Use `-PtalkDockDemo=true` consistently for all Android commands if testing an isolated demo package.

Physical-device checks still needed before release: Samsung keyboard/font settings, real microphone recognition (in-card replies and 말로 물어보기) and live speech playback, including the spoken reply suggestion. Mocked tests verify controls and request sequencing, not external service quality.
