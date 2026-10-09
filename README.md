# 토닥 (Talk Dock)
AI-Powered Family Communication Manager (SNU SWPP 2026)

A mobile app for Korean families to share photos and updates with older adults, listen to AI-adapted messages, send voice replies, and review summaries.

## Structure

```text
client/                 Android app (placeholder)
backend/
  configs/              Django settings and API routes
  apps/accounts/        Account registration and authentication
  apps/families/        Family room models and APIs
  apps/posts/           Photo posts and family feed
  apps/replies/         Text comments; voice replies planned
  apps/digests/         Daily digest TODO
  integrations/ai/      AI adapter for viewer-specific post messages
  integrations/speech/  ElevenLabs speech playback for adapted messages
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

## Iteration 1 - TODO

## Iteration 1 - Limitations

