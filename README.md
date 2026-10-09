# 토닥 (Talk Dock)
AI-Powered Family Communication Manager (SNU SWPP 2026)

A mobile app for Korean families to share photos and updates with older adults, listen to AI-adapted messages, send voice replies, and review summaries.

## Structure

```text
client/                 Kotlin Android app (accounts, family, posts, voice, digest)
backend/
  configs/              Django settings and API routes
  apps/accounts/        Account registration and authentication
  apps/families/        Family room models and APIs
  apps/posts/           Photo posts and family feed
  apps/replies/         Text comments and reviewed voice replies
  apps/digests/         Daily summaries and scheduler
  integrations/ai/      AI adapter for viewer-specific post messages
  integrations/speech/  ElevenLabs speech playback and voice recognition
  developer/            Developer tools and sample data TODOs
  media/                Uploaded images and cached speech
```

## Quick Start

From the repository root, install the backend dependencies (Python 3.11+):
```bash
python -m pip install -r backend/requirements.txt
cp .env.example .env
```
The server reads process environment variables in `.env`. 

```bash
python backend/manage.py migrate
python backend/manage.py runserver 127.0.0.1:8000
```

Open `client/` in Android Studio with JDK 21 and Android SDK 36. The debug app connects to `http://10.0.2.2:8000/api/` on an emulator. 

## APIs
### Account APIs

Send JSON request bodies for registration and login. Protected endpoints require `Authorization: Bearer <token>`; registration and login return a token along with `user_id`, `username`, `name`, and `gender`.

| Endpoint | Authentication | Request body | Result |
| --- | --- | --- | --- |
| `POST /api/accounts/register/` | Not required | `username`, `password`, `name`, optional `gender` (`unknown`, `male`, `female`) | Creates an account and returns its profile and token. |
| `POST /api/accounts/login/` | Not required | `username`, `password` | Returns the account profile and a new token. |
| `POST /api/accounts/logout/` | Required | None | Revokes the presented token; returns `{"ok": true}`. |
| `GET /api/accounts/me/` | Required | None | Returns the current account profile without a token. |

Tokens expire after 30 days. Logging out revokes only the token used for that request.

### Family APIs

Family rooms use the accounts created through `/api/accounts/register/`. Creating or joining a room attaches the authenticated user to it; it does not create another account. Send the account token as `Authorization: Bearer <token>` for the protected endpoints.

| Endpoint | Authentication | Request body | Result |
| --- | --- | --- | --- |
| `POST /api/families/create/` | Required | `room_name`, `password`, optional `digest_time` (`HH:MM`) | Creates a room and owner membership; returns `room`. |
| `POST /api/families/lookup/` | Not required | `invite_code`, `password` | Returns room information when the invitation matches. |
| `POST /api/families/join/` | Required | `invite_code`, `password`, `slot` | Adds the current account as a member; returns `room`. |
| `GET /api/families/current/` | Required | None | Returns the current user's family room. |
| `PATCH /api/families/current/` | Required; owner only | `digest_time` (`HH:MM`) | Changes the room's digest time. |

Room passwords are hashed in the database. A room currently permits one user per family slot; see `backend/apps/families/TODO.md` for the multiple-children limitation.

### Post APIs

All post endpoints require a bearer token and a family membership. Upload a photo with `multipart/form-data`; `caption` is optional.

| Endpoint | Result |
| --- | --- |
| `GET /api/posts/` | Lists up to 100 posts in the current family room, newest first. |
| `POST /api/posts/` | Creates a post from `image` and optional `caption`; returns the new post (200). |
| `GET /api/posts/<id>/` | Returns a post in the current family room. |
| `GET /api/posts/<id>/image/` | Streams its photo only to members of that room. |
| `GET /api/posts/<id>/message/` | Generates or returns the viewer's cached AI message from the photo and caption. |
| `POST /api/posts/<id>/message/` | Retries a failed AI message for the same viewer. |
| `POST /api/posts/<id>/comments/` | Adds a text comment to a post in the current family room; JSON body: `{"text": "..."}` (up to 2,000 characters). |

Uploads are limited to 10 MB, 20 million source pixels, and 2,000 caption characters. Photos are converted to JPEG and resized to at most 1600 × 1600 pixels. Set `PUBLIC_ORIGIN` to the backend's HTTPS address when clients need absolute image URLs through a tunnel. Set `OPENAI_API_KEY` on the backend to enable AI messages; `OPENAI_MODEL` defaults to `gpt-4.1-mini`. The feed includes each post's `comment_count`; post detail includes its comment list with author, relationship, text, source, and creation time.

### Speech API

After `GET /api/posts/<id>/message/` returns `{"status": "ready", "text": "..."}`, send that text as JSON to `POST /api/speech/` with the same bearer token. The response is `audio/mpeg` MP3 data. A family membership is required, and text is limited to 4,000 characters. Configure `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` on the backend; `ELEVENLABS_TTS_MODEL` defaults to `eleven_multilingual_v2`. Generated audio is cached under `backend/media/speech/` by family room, text, model, and voice.

### Voice Reply APIs

Voice replies use three authenticated requests for a post in the user's family room:

| Endpoint | Request body | Result |
| --- | --- | --- |
| `POST /api/posts/<id>/replies/transcribe/` | `multipart/form-data` with `audio` (up to 5 MB; M4A/MP4, WAV, Ogg, or WebM) | Returns `recognized` text from ElevenLabs STT. |
| `POST /api/posts/<id>/replies/prepare/` | JSON `{"recognized": "..."}` (up to 2,000 characters) | Rewrites the recognized speech with OpenAI and saves a draft; returns its `id`, `converted` text, and post details for review. |
| `POST /api/replies/<draft_id>/send/` | None | Publishes the reviewed draft as a voice-sourced comment. Repeating this request returns the same comment. |

The client should show `converted` to the user before sending. Set `ELEVENLABS_API_KEY` and `OPENAI_API_KEY` on the backend; `ELEVENLABS_STT_MODEL` defaults to `scribe_v2`. Uploaded recordings are sent to ElevenLabs and are not stored by the backend.

### Daily Digest APIs

Daily digests summarize posts in one family room from the previous digest time up to the chosen day's digest time (exclusive), using Asia/Seoul time. The default time is 21:00 and the room owner can change it through `PATCH /api/families/current/`. Set `OPENAI_API_KEY` for nonempty summaries.

| Endpoint | Result |
| --- | --- |
| `GET /api/digests/?date=YYYY-MM-DD` | Returns the room's digest for that date, or `pending` before its scheduled time. Omitting `date` selects today in Korea. |
| `POST /api/digests/` | With JSON `{"date": "YYYY-MM-DD"}`, retries a failed digest. |
| `GET /api/digests/history/` | Lists dates with posts or saved digests, plus today. |

Digest responses include `date`, `status` (`pending`, `processing`, `ready`, `empty`, or `failed`), `text`, `digest_time`, and the included `posts`. Completed summaries are cached. To play a ready digest, send its text to the existing `POST /api/speech/` endpoint. Start the scheduler as a separate process after migration; it checks rooms every 30 seconds. Use `--once` for one pass:

```bash
python backend/manage.py run_digest_scheduler
python backend/manage.py run_digest_scheduler --once
```

## Iteration 1 - Limitations and TODO

### Photos and feed

- [ ] **Edit a published photo:** A post currently stores one image (`Post.image`), and there is no update API. Design and implement a way to replace or remove a photo after publication. This is separate from choosing a different photo before posting.
- [ ] **Upload multiple photos:** Add a data model, upload API, and feed/detail navigation for multiple photos in one post.
- [ ] **Decide how photos should open and fit:** Tapping a feed photo currently opens the detail or listening screen, with no full-screen view. Compare full-screen viewing, aspect-ratio preservation, and square frames with padding on real phones.

### Older adult experience and accessibility

- [ ] **Shorten the path to comments:** In the large-text feed, users must open the listening and reply screen before they can start a voice reply. Place text and voice comment options closer to the post, then test whether older adults can find them unaided.
- [ ] **Consolidate audio controls:** Playback and stop, as well as recording start and finish, use separate buttons or actions. Use a single control that clearly reflects the current state, and test playback, recording, and error states.
- [ ] **Continue usability testing:** Check button size, wording, wait times, and recovery from mistakes in addition to text size. Record daily use and feedback.

### Accounts and family relationships

- [ ] **Edit account details:** The account API currently supports registration, login, logout, and read-only profile access. Define which fields can change (name, gender used for relationship labels, and password), the reauthentication rules, and the corresponding screen and API.
- [ ] **Expand the relationship model:** Relationships are computed from eight fixed slots around the room owner. Some relationships between non-owner members display only “family,” and a second person cannot join the same slot (for example, a second son). Model relationships explicitly and revise display rules (see `backend/apps/families/`).

### AI messages and speech

- [ ] **Add family context to adapted messages:** The current adaptation receives only the author's name, relationship, caption, and photo. Define how to explain family members and unfamiliar terms (such as game jargon) to older adults. Evaluate accuracy, context length, and cost. Explicit prompt caching and context compression are not implemented.
- [ ] **Improve voice reply rewriting:** `rewrite(recognized, name)` receives only the transcribed words and post author's name. Add relevant family relationships and forms of address, and test whether names, numbers, negation, and conditions retain their meaning. Measure Korean proper-name errors in STT separately.
- [ ] **Personalize and evaluate TTS:** The TTS voice ID and model are server-wide settings; only the cache key is separated by family room. Compare Korean pronunciation and speaking speed across models, then add a stored voice preference for each listener.
- [ ] **Decide whether to share original recordings:** Voice replies currently publish the STT/LLM-converted **text comment**, not the recording. Use requirements and user testing to decide whether families should hear the original audio; if so, design storage and playback.
- [ ] **Define an evaluation plan for the main AI feature:** Choose a primary problem, such as name recognition or family-context delivery, and create test cases, metrics, and model/prompt comparisons. Build a reusable test bed from observed failures.

## AI-Collaboration-Report

AI generated the project's code. Because this applies to nearly the entire codebase, we disclose it here instead of adding AI attribution comments to individual files. The team provided detailed requirements for each app's responsibilities, module boundaries, and refactoring, then read and reviewed the generated code. Issues found during that review informed much of the [Iteration 1 limitations and TODO list](#iteration-1---limitations-and-todo).

See the [AI Collaboration Report](https://github.com/DaehyeopKim/SWPP_team12/wiki/AI-Collaboration-Report) for more details.

