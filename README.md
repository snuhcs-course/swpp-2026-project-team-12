# 토닥 (Talk Dock)
AI-Powered Family Communication Manager (SNU SWPP 2026)

A mobile app for Korean families to share photos and updates with older adults, listen to AI-adapted messages, send voice replies, and review summaries.

## Demo Video

- [Iteration 1 demo video, 정아's view](./T12_demo_video_1.mp4)
- [Iteration 1 demo video, 할머니's view](./T12_demo_video_2.mp4)

## Structure

```text
client/                 Kotlin Android app (accounts, family, posts, voice, digest)
web/                    Desktop web UI, integrated launcher, and setup guide
backend/
  configs/              Django settings and API routes
  apps/accounts/        Account registration and authentication
  apps/families/        Family room models and APIs
  apps/posts/           Photo posts and family feed
  apps/replies/         Text comments and reviewed voice replies
  apps/digests/         Daily summaries and scheduler
  apps/searching/       Family history search and construction worker
  integrations/ai/      LLM adapters and shared 2-way/3-way flow
  integrations/ai_workers/ Graphiti construction, retrieval, and worker management
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

# Run Graphiti Construction Worker
python backend/manage.py run_construction_worker --family-id 12
# Note that Searching Workers are automatically started when the first searching occurs.
```

Open `client/` in Android Studio with JDK 21 and Android SDK 36. The debug app connects to `http://10.0.2.2:8000/api/` on an emulator. 

## Family tree data and invitation API

`FamilyPerson` represents a person independently of an account. `ParentChild` stores directed parent-to-child links, `Partnership` stores explicit spouse links, and `Membership.person` connects an account to one person. `FamilyRoom.owner` controls room administration. Memberships require a person; the former owner-relative slot field is removed. Relationship labels are resolved by graph search in `backend/apps/families/utils/relationships.py`.

`POST /api/families/lookup/` returns the room and `tree` snapshot (`version`, `owner_id`, `people`, `parents`, `partnerships`). Person IDs are strings. To join, submit the invitation credentials and the snapshot version, selected person, and sequential additions:

```json
{
  "invite_code": "ABC123",
  "password": "room-password",
  "tree_version": 0,
  "person_id": "new_me",
  "additions": [
    {"id": "new_parent", "anchor_id": "1", "relation": "father"},
    {"id": "new_me", "anchor_id": "new_parent", "relation": "child"}
  ]
}
```

Supported additions are `father`, `mother`, `parent` (unspecified), `spouse`, and `child`. A child can specify `co_parent_id` for an existing spouse or co-parent. Only new people can be added; existing graph data cannot be rewritten by an invitation draft. At most 200 people can be added per join. Selecting an existing unclaimed person uses its ID with an empty additions list. A conditional version update and transaction prevent partial saves; stale or occupied positions return HTTP 409. Reload the tree and start again.

Family migrations start directly with the tree schema. When updating an older local database that used slots, reset `backend/db.sqlite3` and run `python backend/manage.py migrate`; existing data is not imported. Parent edges always move one generation upward, and a person has at most two parents in this version. Ages are not collected, so sibling labels stay neutral instead of guessing Korean age-specific honorifics.

## Graphiti family history

Graphiti stores each family's post history in Neo4j. Start Neo4j and configure
`OPENAI_API_KEY`, `NEO4J_URI`, `NEO4J_USER`, and `NEO4J_PASSWORD` in `.env`.

### Construction (storing posts)

Run this in a separate terminal for each family and keep it running:

```powershell
python backend/manage.py run_construction_worker --family-id 12
```

Uploading a post saves it to the app DB. The worker finds posts not yet stored in
Graphiti, processes up to 100 author/caption records in creation order, then waits
5 seconds before checking again. Uploads do not enqueue work directly.
Add `--once` to process one batch and exit; use `Ctrl+C` to stop a running worker.

Before posts, the worker syncs confirmed family members and their relationships.
Creation, joining, and name edits leave a pending tree version; failures retry on
the next pass. `FamilyPerson.graphiti_uuid` keeps each member's node identity.
An unclaimed node is reused only when its name is unique in both the room's graph
and member list. Ambiguous names get separate nodes. Relationships have stable
UUIDs and `family_registry_<room>_v<version>` source episodes, without creating posts.

### Search (retrieving history)

Search and AI requests submit work to a shared thread pool inside the Django
process and wait for the result. Threads are reused across families, while each
request searches only its own family's records. No separate search command is needed.

Family history uses `search -> LLM`. Basic post summaries use only the current
post and photos. Additional questions use `LLM -> search -> LLM`, skipping
retrieval when the LLM can answer from the current input alone.

### Post feed and additional questions

The feed returns the latest 100 posts, ordered by creation time and then ID, both
descending. The Android client also sorts responses by the same rule.

Tap **AI 요약** to display the post summary without playing audio. Listening uses
the same summary and reuses it if already loaded. Voice replies remain available
in post detail.

Tap **궁금한 점을 물어보세요** on a feed card or below the summary controls in post detail to
ask about that post. Answers appear in the same detail screen. Successful turns
remain visible while the detail screen stays open; follow-up requests include
the last five question/answer pairs, with each message limited to 1,000 characters.
Leaving the detail screen clears this conversation. Questions are separate from
family comments, and failed requests keep the typed question for retry.

## APIs
### Account APIs

Send JSON request bodies for registration and login. Protected endpoints require `Authorization: Bearer <token>`; registration and login return a token along with `user_id`, `username`, `name`, and `gender`.

| Endpoint | Authentication | Request body | Result |
| --- | --- | --- | --- |
| `POST /api/accounts/register/` | Not required | `username`, `password`, `name`, required `gender` (`male` or `female`) | Creates an account and returns its profile and token. |
| `POST /api/accounts/login/` | Not required | `username`, `password` | Returns the account profile and a new token. |
| `POST /api/accounts/logout/` | Required | None | Revokes the presented token; returns `{"ok": true}`. |
| `GET /api/accounts/me/` | Required | None | Returns the current account profile without a token. |

Tokens expire after 30 days. Logging out revokes only the token used for that request.

### Family APIs

Family rooms use the accounts created through `/api/accounts/register/`. Creating or joining a room attaches the authenticated user to it; it does not create another account. Send the account token as `Authorization: Bearer <token>` for the protected endpoints.

| Endpoint | Authentication | Request body | Result |
| --- | --- | --- | --- |
| `GET /api/families/` | Required | None | Lists the user's rooms as `rooms` (`id`, `name`, `is_owner`, `member_count`) in join order. |
| `POST /api/families/create/` | Required | `room_name`, `password`, optional `digest_time` (`HH:MM`) | Creates a room and owner membership; returns `room`. |
| `POST /api/families/lookup/` | Not required | `invite_code`, `password` | Returns room information when the invitation matches. |
| `POST /api/families/join/` | Required | `invite_code`, `password`, `tree_version`, `person_id`, `additions` | Adds the current account as a member; returns `room`. Joining a room twice returns 409. |
| `GET /api/families/current/` | Required | None | Returns the selected family room. |
| `PATCH /api/families/current/` | Required; owner only | `digest_time` (`HH:MM`) | Changes the selected room's digest time. |

Room passwords are hashed in the database. Each tree person can be claimed by one account; multiple children of the same gender are supported.

An account can create and join several rooms. Room-scoped endpoints (`families/current/`, `GET`/`POST /api/posts/`, `digests/`, `searching/`, `speech/`) use the room named by the `X-Family-Room: <room id>` header and return 403 when the header is missing or names a room the account does not belong to. Endpoints under `/api/posts/<id>/` and `/api/replies/` use the post's own room and need no header.

### Post APIs

All post endpoints require a bearer token and membership in the post's room. Upload with `multipart/form-data`: a non-blank `caption`, up to five repeated `images` files, or both. The legacy single-file `image` input remains accepted; do not mix it with `images`.

| Endpoint | Result |
| --- | --- |
| `GET /api/posts/` | Lists up to 100 posts in the current family room, newest first. |
| `POST /api/posts/` | Creates a text-only or multi-photo post; returns the new post (200). |
| `GET /api/posts/<id>/` | Returns a post in the current family room. |
| `GET /api/posts/<id>/images/<index>/` | Streams a photo at its zero-based position only to members of that room. |
| `GET /api/posts/<id>/image/` | Compatibility alias for the first photo; 404 for text-only posts. |
| `GET /api/posts/<id>/message/` | Generates or returns the viewer's cached AI message from the photo and caption. |
| `POST /api/posts/<id>/message/` | Retries a failed AI message for the same viewer. |
| `POST /api/posts/<id>/questions/` | Answers a question about the post; JSON body: `question` (up to 1,000 characters) and optional `prior_dialogue` (up to 10 user/assistant messages, each with `role` and `text`, up to 1,000 characters). Returns `text`. |
| `POST /api/posts/<id>/comments/` | Adds a text comment to a post in the current family room; JSON body: `{"text": "..."}` (up to 2,000 characters). |

Uploads are limited to 10 MB and 20 million source pixels per photo, 30 MB combined, and 2,000 caption characters. Photos are converted to JPEG and resized to at most 1600 × 1600 pixels. Set `PUBLIC_ORIGIN` to the backend's HTTPS address when clients need absolute image URLs through a tunnel. Set `OPENAI_API_KEY` on the backend to enable AI messages; models default to `DEFAULT_AI_*` and can be overridden per feature group (`SUMMARY_AI_*`, `STT_AI_*`, `ANSWER_AI_*`, `QUERY_AI_*`, `GRAPHITI_*`); see `.env.example`. The feed includes each post's `comment_count`; post detail includes its comment list with author, relationship, text, source, and creation time.

Photo paths are stored in one ordered `Post.images` JSON list. The API still returns an `images` array of `{id, url}` objects and `image_count`; each image `id` is now its position within that post, not a global photo ID. Clients must use the supplied URL. The old `/photos/<photo_id>/` route has been removed; refresh browser tabs after updating the backend and web assets together. Android already uses the supplied URLs.

When upgrading from the current tree-based family schema, stop the API server and construction/digest workers, back up the database and media, then run `python backend/manage.py migrate` before restarting them. `posts.0006_post_images` collects the former cover followed by attachments ordered by `(position, id)`, removes `Post.image` and `PostPhoto`, and keeps the actual files in place. It preserves post IDs, creation times, descriptions, and cached summaries. Reversing this migration preserves file paths and order but assigns new attachment IDs. This photo migration does not require a database reset; the separate historical family-schema reset described above still applies only to slot-based databases.

### Speech API

After `GET /api/posts/<id>/message/` returns `{"status": "ready", "text": "..."}`, send that text as JSON to `POST /api/speech/` with the same bearer token. The response is `audio/mpeg` MP3 data. A family membership is required, and text is limited to 4,000 characters. Configure `ELEVENLABS_API_KEY` on the backend. The voices accounts can choose are listed once in `TTS_VOICES` in `backend/configs/settings.py`, each with a `name`, an ElevenLabs `voice_id` and a `description`; entries without a `voice_id` are not offered. `GET /api/speech/voices/` (no login) returns each offered voice's key, name and description and the default, and the apps build their choices from it, so adding a voice needs only a new `TTS_VOICES` entry. Each account may pick a voice key as `tts_voice` at registration and can change it with `PATCH /api/accounts/me/` `{"tts_voice": "<key>"}`; accounts that never chose one follow `TTS_DEFAULT_VOICE`, which must be a `TTS_VOICES` key (`manage.py check` reports it otherwise). Each voice has a preview sample reading "가족의 일상을 잇는 따뜻한 공간, 토닥" at `GET /api/speech/voices/<key>/sample/` (no login); samples live in `backend/integrations/speech/samples/` named by voice ID, so after adding a voice or changing its `voice_id`, run `python backend/manage.py generate_voice_samples` (needs `ELEVENLABS_API_KEY`) and commit the new MP3, and `/api/speech/` uses the requesting account's choice; `ELEVENLABS_TTS_MODEL` defaults to `eleven_multilingual_v2`. Generated audio is cached under `backend/media/speech/` by family room, text, model, and voice.

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

- [ ] **Edit a published photo:** Photos are stored in `Post.images`, and there is no update API. Design and implement a way to replace or remove a photo after publication. This is separate from choosing a different photo before posting.
- [x] **Upload multiple photos:** Up to five ordered photos per post, with feed/detail navigation and unified path storage.
- [ ] **Decide how photos should open and fit:** Tapping a feed photo currently opens the detail or listening screen, with no full-screen view. Compare full-screen viewing, aspect-ratio preservation, and square frames with padding on real phones.

### Older adult experience and accessibility

- [ ] **Shorten the path to comments:** In the large-text feed, users must open the listening and reply screen before they can start a voice reply. Place text and voice comment options closer to the post, then test whether older adults can find them unaided.
- [ ] **Consolidate audio controls:** Playback and stop, as well as recording start and finish, use separate buttons or actions. Use a single control that clearly reflects the current state, and test playback, recording, and error states.
- [ ] **Continue usability testing:** Check button size, wording, wait times, and recovery from mistakes in addition to text size. Record daily use and feedback.

### Accounts and family relationships

- [ ] **Edit account details:** The account API currently supports registration, login, logout, and read-only profile access. Define which fields can change (name, gender used for relationship labels, and password), the reauthentication rules, and the corresponding screen and API.
- [x] **Expand the relationship model:** People, parent/child links, and partnerships form the family tree. Relationship labels are found from that graph, including through people without accounts.

### AI messages and speech

- [ ] **Add family context to adapted messages:** The current adaptation receives only the author's name, relationship, caption, and photo. Define how to explain family members and unfamiliar terms (such as game jargon) to older adults. Evaluate accuracy, context length, and cost. Explicit prompt caching and context compression are not implemented.
- [ ] **Improve voice reply rewriting:** `rewrite(recognized, name)` receives only the transcribed words and post author's name. Add relevant family relationships and forms of address, and test whether names, numbers, negation, and conditions retain their meaning. Measure Korean proper-name errors in STT separately.
- [ ] **Personalize and evaluate TTS:** The TTS voice ID and model are server-wide settings; only the cache key is separated by family room. Compare Korean pronunciation and speaking speed across models, then add a stored voice preference for each listener.
- [ ] **Decide whether to share original recordings:** Voice replies currently publish the STT/LLM-converted **text comment**, not the recording. Use requirements and user testing to decide whether families should hear the original audio; if so, design storage and playback.
- [ ] **Define an evaluation plan for the main AI feature:** Choose a primary problem, such as name recognition or family-context delivery, and create test cases, metrics, and model/prompt comparisons. Build a reusable test bed from observed failures.

## AI-Collaboration-Report

AI generated the project's code. Because this applies to nearly the entire codebase, we disclose it here instead of adding AI attribution comments to individual files. The team provided detailed requirements for each app's responsibilities, module boundaries, and refactoring, then read and reviewed the generated code. Issues found during that review informed much of the [Iteration 1 limitations and TODO list](#iteration-1---limitations-and-todo).

See the [AI Collaboration Report](https://github.com/DaehyeopKim/SWPP_team12/wiki/AI-Collaboration-Report) for more details.

