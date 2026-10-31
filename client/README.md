# Android app

Open `client/` in Android Studio with JDK 21 and Android SDK 36. The app uses Kotlin and Android View. Build the debug APK with:

```sh
./gradlew :app:assembleDebug :app:lintDebug
```

To build both APKs together, run `./gradlew :app:assembleApks` (Windows: `.\gradlew.bat :app:assembleApks`) from `client/`.
The files are written to `app/build/outputs/apk/distribution/`:

- `talkdock_local_dev.apk`: the existing debug build, using `http://10.0.2.2:8000/api/` by default or `-PtalkDockApiUrl=...`.
- `talkdock.apk`: a release build using `PUBLIC_ORIGIN` from the repository-root `.env`, with `/api/` appended. An exported `PUBLIC_ORIGIN` takes precedence. For example, `PUBLIC_ORIGIN=https://api.talkdock.app` connects to `https://api.talkdock.app/api/`. It requires an HTTPS origin and has no debug connection settings.

Both APKs use the existing development signing certificate for direct APK sharing; configure a private release signing key before publishing to an app store. They have the same application ID, so installing one replaces the other. Local and public builds keep separate account sessions. `DJANGO_ALLOWED_HOSTS` is a backend setting and must include the public hostname (e.g. `api.talkdock.app`). Only the public origin is embedded in the release APK; backend secrets stay in `.env`.

Start the Django server from the repository root with `python backend/manage.py runserver 127.0.0.1:8000`. The emulator connects through the default `http://10.0.2.2:8000/api/` address. On the first screen, create an account with a unique username, a password of at least 10 characters, and a display name, and a required gender selection. After registration, create a family room or join one using its invitation code, room password, and an unclaimed position in the family tree. Existing accounts can log in with their username and password. The app stores account tokens on the device for switching accounts; an expired token opens login again with the username filled in. **Log out** revokes the current token and removes that local account session.

## Family tree invitations

After verifying the invitation code and room password, drag the tree horizontally or vertically to explore it. Dotted `+` nodes add an unclaimed person; tapping a white person separately selects your own position. Parents, spouses, and children can be added. Add another child of a parent to represent a sibling. Blank people also expose their own one-step additions, so intermediate relatives do not need app accounts.

The draft stays on the device until **가족 방에 들어가기**. **추가 취소** undoes the latest added person; leaving the setup discards the draft. Joining atomically saves the people, relationships, and account link. If another join changed the tree version, the app discards the stale draft and reloads the latest tree. Existing occupied positions cannot be claimed.

## USB device

Enable USB debugging and connect the device. With the backend on the same computer:

```sh
adb reverse tcp:8000 tcp:8000
./gradlew :app:assembleDebug -PtalkDockApiUrl=http://127.0.0.1:8000/api/
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

Run `adb reverse` again after reconnecting the device. To use a remote HTTPS backend, build with `-PtalkDockApiUrl=https://your-host/api/` or enter its address in **테스트 연결 설정** in the debug app. Changing the server clears the device's saved account sessions; log in again on the new server. Debug builds allow local HTTP; release builds require HTTPS.

## App features

The family home is a stack of warm, rounded **photo letters**. Swipe left/right or use the previous/next arrows to change the current post; the counter and floating assistant follow that post. Only the active letter's cover is mounted. The author initials/name and date share the footer, leaving space on the assistant's current edge. Pull down to refresh. Tap a photo or caption to open the full post, browse all original-ratio photos, read comments, or reply by text/voice. Listening and AI summaries are in the floating assistant menu. The letter cover is cropped for the postcard; detail and full-photo views preserve the original composition.

The main navigation has **소식** and **하루**. The `+` in the header creates a post. The initials circle opens **프로필 → 설정**, family-room switching, and account switching; settings retain account editing, family invitations/tree, text size, digest schedule, logout, and debug connection settings. Accounts currently have no profile-photo field, so the profile control uses the account's initial.

The home exposes one primary action, **말로 답장하기**. It opens a recording page for the current letter and requests microphone permission when necessary. Stopping records and transcribes the draft, then retains the existing review-before-send workflow. The listening animation shows elapsed recording time, not live transcription. Back cancels the recording without uploading it.

**하루** presents the selected date's digest as one journal page, up to three clickable photo/text covers, a single play/stop control, and links to any remaining source posts. Date selection and pending/empty/error recovery remain available. AI/STT/TTS keys stay on the backend.

The selected font combination is **학교안심 둥근미소 R** for the top-left **토닥** brand title and **Pretendard Medium** for the rest of the UI (sample 11). Both files are bundled under `app/src/main/res/font/`; their embedded notices are preserved in `app/src/main/assets/SELECTED-FONT-NOTICES.txt`. The UI keeps white backgrounds, warm brown text, coral/peach/beige accents, and rounded controls. Cards and dialogs stay white, while supporting panels and inputs retain the warm tints. The shared palette is in `app/src/main/res/values/colors.xml` and is used by both the Kotlin UI and Android window/system-bar themes. The existing NanumSquareRound and Noto resources and license notices remain in the project.

The HTTP client is `app/src/main/java/kr/talkdock/app/data/ApiClient.kt`, account sessions are in `data/SessionStore.kt`, shared UI is in `ui/Ui.kt`, and recording and playback are in `device/Voice.kt`. Font licenses are in `FONT-LICENSE.txt` and `NANUM-FONT-LICENSE.txt`.

## Android tests

With Django running and an emulator or USB device connected, run:

```sh
./gradlew :app:connectedDebugAndroidTest
```

The HTTP test registers two accounts, logs one in, creates and joins a family room, uploads a photo, checks the protected image, and exchanges a text comment. It leaves those test accounts, room, and post in the server database. The recorder test checks local M4A recording and cancellation on the device.

## In-place post audio

The floating assistant's **음성으로 듣기** action fetches the selected post's AI summary and then
plays its generated speech. The same menu shows **듣기 중지** during playback or preparation.
Its separate **AI 요약 보기** action shows the summary without requesting speech.
From home, either action first opens that post's detail. The detail header has no audio or summary controls. Only one post plays at a time.
Summary text, loading, errors, retry, and original-caption fallback appear below
the post. Summary and speech requests use the separate summary executor so
comment actions remain available. Leaving the detail page or backgrounding the app
invalidates pending results and stops playback; refresh also releases old panels.
While the post summary is being prepared, an unboxed **가족 소식 준비중** row shows three gently animated dots. During speech generation, the same layout shows **목소리 생성중** with a five-bar waveform below the summary. The indicators disappear when preparation finishes, stops, or fails; their animations pause when hidden and respect disabled system animations. Server-side processing retains the compact news indicator and the existing manual recheck action.
The old listening screen now restores to post detail, voice-comment cancellation
returns to post detail, and digest links open post detail in both text sizes.

Run the local-server regression tests (generated WAV audio, no AI/TTS API calls):

```sh
./gradlew :app:connectedDebugAndroidTest \
  -Pandroid.testInstrumentationRunnerArguments.class=kr.talkdock.app.InlinePostAudioTest
```

## Comment input

Post detail uses a compact multiline comment field with a microphone when empty and a Send arrow when text is entered (48dp, or 64dp in large-text mode). The input reserves space beside the controls and scrolls into view above the software keyboard; Enter inserts a newline. Blank input and pending submissions disable
Send. A local progress indicator replaces the full-screen wait overlay.
Only an accepted submission clears the input and refreshes the comment list.
HTTP, network, and expired-login errors stay below the input and preserve the
exact draft for editing or retry; voice commenting starts from the input microphone.

`CommentComposerTest` verifies both text sizes, whitespace-only input, multiline
content, duplicate-click protection, draft retention after failure, retry with
the identical content, and successful comment-list refresh using a local server.

Reply review places a single play/stop icon beside the converted comment heading;
it keeps Send and Re-record, with the back arrow available to leave the screen.
Post audio shows summary text and loading/error recovery without separate
playing, stopped, or completed message cards.

## Photo-letter design validation

`PhotoLetterDesignTest` uses an isolated local HTTP server and bundled test photo. It checks real horizontal swipes, post-specific assistant questions, opening all photos in detail, profile/settings navigation, both text sizes on the daily screen, and cancelling a voice draft without sending it. It saves actual emulator screenshots to app cache. Run:

```sh
./gradlew :app:testDebugUnitTest :app:lintDebug :app:connectedDebugAndroidTest \
  -Pandroid.testInstrumentationRunnerArguments.class=kr.talkdock.app.PhotoLetterDesignTest
```

The compact detail composer keeps text drafts on failed requests and reserves space beside its send/microphone controls. Text input, photo picking, gallery order and the reviewed voice-reply APIs continue using the existing backend endpoints.

Local validation on 2026-10-30 passed 33 JVM tests, 89 device UI tests, and the local Django API round-trip test. Debug/release APKs and Android Lint passed. For a local API test server, clear `PUBLIC_ORIGIN` in that process so uploaded-photo URLs resolve to the local server rather than the public deployment; use a temporary `DJANGO_DB_PATH` and `DJANGO_MEDIA_ROOT` to isolate test accounts/uploads.
