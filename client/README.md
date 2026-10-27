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

The family feed shows photos and text, with a refresh button beside the camera button. Post photos fit within a square area without cropping. A family member can replace a selected photo from the camera or gallery before publishing it, then leave a text or voice comment directly from the post detail screen. Older members can read an AI-adapted message, play it through server-side TTS, record an M4A voice reply, review the recognized and rewritten text, and send it as a comment. The daily digest screen shows the selected day's summary and can play it through the same TTS endpoint. AI, STT, and TTS keys stay on the backend. Recording needs microphone permission; camera capture uses the device camera app.

The HTTP client is `app/src/main/java/kr/talkdock/app/data/ApiClient.kt`, account sessions are in `data/SessionStore.kt`, shared UI is in `ui/Ui.kt`, and recording and playback are in `device/Voice.kt`. The bundled Noto Sans KR font license is in `FONT-LICENSE.txt`.

## Android tests

With Django running and an emulator or USB device connected, run:

```sh
./gradlew :app:connectedDebugAndroidTest
```

The HTTP test registers two accounts, logs one in, creates and joins a family room, uploads a photo, checks the protected image, and exchanges a text comment. It leaves those test accounts, room, and post in the server database. The recorder test checks local M4A recording and cancellation on the device.

## In-place post audio

The speaker action on the feed and post detail fetches the AI summary and then
plays its generated speech without opening another screen. Pressing it again
stops playback or cancels pending playback. Only one post plays at a time.
Summary text, loading, errors, retry, and original-caption fallback appear below
the post. Summary and speech requests use the separate summary executor so
comment actions remain available. Leaving the page or backgrounding the app
invalidates pending results and stops playback; refresh also releases old panels.
The old listening screen now restores to post detail, voice-comment cancellation
returns to post detail, and digest links open post detail in both text sizes.

Run the local-server regression tests (generated WAV audio, no AI/TTS API calls):

```sh
./gradlew :app:connectedDebugAndroidTest \
  -Pandroid.testInstrumentationRunnerArguments.class=kr.talkdock.app.InlinePostAudioTest
```

## Comment input

Post detail uses a multiline comment field with a Send arrow in the bottom-right
corner (48 dp, or 64 dp in large-text mode). The footer keeps the action clear of
long text and scrolls into view above the software keyboard; Enter inserts a newline. Blank input and pending submissions disable
Send. A local progress indicator replaces the full-screen wait overlay.
Only an accepted submission clears the input and refreshes the comment list.
HTTP, network, and expired-login errors stay below the input and preserve the
exact draft for editing or retry; voice commenting remains below the field.

`CommentComposerTest` verifies both text sizes, whitespace-only input, multiline
content, duplicate-click protection, draft retention after failure, retry with
the identical content, and successful comment-list refresh using a local server.

Reply review places a single play/stop icon beside the converted comment heading;
it keeps Send and Re-record, with the back arrow available to leave the screen.
Post audio shows summary text and loading/error recovery without separate
playing, stopped, or completed message cards.
