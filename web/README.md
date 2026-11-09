# Talk Dock Web · Share Family Moments on Your PC

A desktop web client served by the **same Django backend and database as the Android app**. Accounts, family rooms, posts, comments, and AI features are shared. Family members without an Android phone can visit the shared server's web address in their browser; they do not need to install or run a server themselves.

No separate frontend server, Node.js installation, or npm build is required.

## 1. Installation

On the server/development PC, open PowerShell in the repository root:

```powershell
cd C:\Users\DaehyeopKim\Desktop\26-2\SWPP\team12_project_public\swpp-2026-project-team-12
conda activate swpp_project
python -m pip install -r web\requirements.txt
```

`web/requirements.txt` includes `backend/requirements.txt`. The web client adds no external Python or JavaScript dependencies. Use Python 3.11 or later and a recent Chrome, Edge, Firefox, or Safari browser.

If Conda activation is unavailable, invoke the environment's Python directly:

```powershell
& "$env:USERPROFILE\miniconda3\envs\swpp_project\python.exe" -m pip install -r web\requirements.txt
& "$env:USERPROFILE\miniconda3\envs\swpp_project\python.exe" web\run.py
```

## 2. Start the Server and Open the App

For a new installation only, copy `.env.example` to `.env`. **Keep your existing `.env` if one is already configured.**

```powershell
if (!(Test-Path .env)) { Copy-Item .env.example .env }
python web\run.py
```

Open **[http://127.0.0.1:8000/](http://127.0.0.1:8000/)** on the server PC. Opening `index.html` directly from File Explorer is not supported. This loopback address is for local development; other users connect to the shared server's actual hostname or IP address.

- The launcher applies database migrations and starts both the web UI and API. There is no additional backend to start.
- If the existing backend is already using port 8000, restart it to load the web changes and use the same address. Starting it with `python backend\manage.py runserver 127.0.0.1:8000` also serves the web UI.
- To use another port: `python web\run.py --port 8001`, then open [http://127.0.0.1:8001/](http://127.0.0.1:8001/).
- From inside the `web` directory, use `python run.py`.
- Stop the server with `Ctrl+C` in its terminal.
- Disable Django's automatic code reload with `--no-reload`.
- Skip database migrations with `--skip-migrate`.

Android emulators continue to use `http://10.0.2.2:8000/api/`. When Android and the browser connect to the same backend, they share the same data. Servers configured to use different databases do not share data.

This branch uses the family tree schema from its initial migration. Before starting it with an older slot-based local database, reset that database and run migrations to create the new schema. Old family data is not imported.

## 3. Using the App

The web interface remains in Korean. The instructions below explain the corresponding controls in English.

1. **Sign in / register:** Use an existing Android account or create a new account. Choose a gender for family relationship labels. Passwords must contain a number and have at least 10 characters. Enter the same password again in the confirmation field; confirmation is checked locally and is never sent to the API.
2. **Connect to a family room:** Create a room, or enter an invitation code and room password. When joining, select an unclaimed person directly on the family tree. The + nodes add parents, spouses, or children with the same generation layout as Android. Drag to move, use the zoom controls or arrow keys to navigate, and undo the last addition when needed. Only empty positions matching your account gender can be selected. One account can belong to one room; each person can be claimed once, and multiple children of the same gender are supported. If the tree changes during joining, reload it and select your position again.
3. **Family feed:** Use the sidebar to view family posts. Click the new-post button to share text and photos. Drag photos into the upload area or select them through the file picker. Each post supports up to five photos, with limits of 10 MB per photo, 30 MB total, and 20 million source pixels per photo. Text-only posts are supported; captions are limited to 2,000 characters.
4. **Post details:** Click a photo or comment button to view photos and comments side by side. Use the thumbnails to switch photos. You can comment, generate or listen to an AI summary, and ask questions about the post. AI questions are separate from family comments, and the conversation resets when the detail dialog closes.
5. **Voice replies:** Click the microphone reply button, allow microphone access, record, and finish recording. Review and optionally correct the transcription, request an AI rewrite, and review the rewritten reply before sending it. Recordings are limited to two minutes and 5 MB. The published comment contains the converted text, not the original audio.
6. **Find memories:** Ask a natural-language question about family history. The feed's filter searches text and author names within the latest 100 loaded posts; the separate memories page searches Graphiti family records.
7. **Daily digest:** Choose a date to read or listen to its digest and open the included posts. Before the room's scheduled digest time in Korea, the digest is pending. Run the scheduler described below for automatic generation.
8. **Family / account settings:** View the family tree with parent/child and spouse connectors, including unclaimed people. Your own position is highlighted and relationship labels are relative to you. Opening this screen or using its refresh button fetches the latest family data. You can also copy the invitation code, change the digest time as the room owner, or update your display name and password. Changing a password through account settings revokes tokens on other devices.

Desktop layouts use persistent sidebar navigation, a wide feed with a family information panel, and a split photo/comment dialog. Narrow screens switch to a single column. The app supports larger text, keyboard navigation, and closing dialogs with Esc.

**Daily conversation questions:** A compact, sticky **오늘의 질문** preview above
the feed shows the current question and an unread dot for new family activity.
It stays separate from posts and filters. Opening it leaves the feed and its
scroll position in place; the desktop dialog places the question and answer
editor beside family responses and shared comments. Narrow screens stack these
sections, and the existing **큰 글씨** setting also applies.

The web uses the same daily-question APIs, JSON catalog, reservations, answers,
and comments as Android. It supports choice, short text, mood weather, and
S/A/B/C tier answers. Choice/weather keep all options visible after submission;
**수정** enables editing, and **기타** reveals a required inline custom field.
Answers are emphasized in colored bold chips; discussion uses shared comments.
**지난 질문** includes pagination and lets members answer or edit older questions.
Answer and comment drafts survive closing/reopening the dialog within the tab,
are separated by question, and are cleared on account/room changes. Failed
submissions keep drafts. Microphone controls transcribe into an editable field
and require an explicit send; they never automatically publish or rewrite a
daily answer. Microphone input uses the existing HTTPS/localhost and speech
service requirements.

Run `node --test web/test_daily_questions.mjs` for offline payload, validation,
escaping, persistent-choice markup, and history checks. The existing
`python backend/manage.py test web developer.test_codes.test_daily_questions`
also checks asset serving and the shared backend contract. Apply the daily
question database migrations before updating an older backend.

The feed's 96px circular character has an orbiting border sparkle (static with reduced motion).
It opens a movable, resizable post-question panel and hides while
the panel is open. Closing the panel restores the character at its saved position. While it is open,
the post closest to the visible feed's center stays bright and the surrounding page is shaded.
Scrolling automatically changes both the highlighted post and its conversation. Each post keeps
its own draft, answers, and pending request; a late answer never appears on another post.
Drag the panel title to move it and use any edge/corner to resize.
The character can be freely dragged anywhere inside the viewport without snapping to an edge. Arrow keys move the focused
character/title or resize a focused edge. Geometry is remembered in `localStorage`; conversations
stay in tab memory and are cleared on account/room changes. Small screens use a bottom panel.
The old right-hand digest card is removed; **하루 모아보기** remains in navigation.
See [the assistant implementation and verification notes](developer/floating-assistant.md).

Loading screens and pending actions use the same boy artwork as Android. The resized PNG artwork is embedded in `assets/styles.css`, using the existing web asset route. Pending actions show a floating status card that also remains visible inside an open dialog. Successful post publication and text/voice comments show a separate, centered confirmation with a gently animated cheerful boy for three seconds. The waiting indicator is hidden during confirmation; reduced-motion preferences disable the animation. Failed submissions keep their drafts and do not show success feedback. The old GIF remains as a legacy served asset but is no longer referenced by the UI.

The login token is stored in the current tab's `sessionStorage`. It survives refreshes and is cleared when the tab session ends. Use the logout button to revoke it immediately on the server. Family photos are fetched with Bearer authentication and displayed through Blob URLs; tokens are never embedded in image URLs or sent to external image hosts.

## 4. AI, Speech, and Family History

Accounts, family rooms, uploads, and text comments do not require AI credentials. Other features use the existing backend and the repository-root `.env`. Do not put secret keys in web assets.

| Feature | Required configuration / process |
| --- | --- |
| Post summaries and questions; nonempty daily digests | `OPENAI_API_KEY` and the existing AI model settings |
| Listening to summaries | `ELEVENLABS_API_KEY`, plus voice IDs in `TTS_VOICES` (`backend/configs/settings.py`) |
| Voice replies | `ELEVENLABS_API_KEY`, `OPENAI_API_KEY`, browser microphone permission |
| Memory search and questions requiring historical context | OpenAI configuration, running Neo4j, `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, and the family construction worker |
| Automatically generating digests at the scheduled time | A separately running `run_digest_scheduler` process |

Run family history construction and the digest scheduler in separate terminals with the same Python environment activated. To find a family room ID, sign in and inspect the `rooms` list in the `/api/families/` response in your browser's Network developer tools. The web app sends the room it shows as the `X-Family-Room` header and remembers the last opened room per account in `localStorage`.

```powershell
# Replace 12 with the actual room ID. Run one worker per family room.
python backend\manage.py run_construction_worker --family-id 12

# In another terminal: check the digest schedules for all rooms.
python backend\manage.py run_digest_scheduler
```

AI actions use the existing API when requested. If credentials or a service are unavailable, the UI displays an error; ordinary posts and comments remain available.

## 5. Access from Another PC on the Same Network

This example assumes the server PC's LAN address is `192.168.0.10`. **Replace it with the actual server IP.** Add that IP to the existing allowed-host list in `.env`, then restart the backend:

```dotenv
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,10.0.2.2,testserver,192.168.0.10
```

```powershell
python web\run.py --host 0.0.0.0 --port 8000
```

Other PCs can then open `http://192.168.0.10:8000/`. If needed, allow port 8000 through Windows Firewall on the trusted private network. `0.0.0.0` is the server's listening address; users enter the actual server IP in their browsers.

Browser microphone access requires **localhost/127.0.0.1 or HTTPS**. Over a plain HTTP LAN connection, text and photo features work, but recording is unavailable. For remote recording, serve the web UI and API together through HTTPS. `PUBLIC_ORIGIN` configures existing Android image URLs; the web client uses authenticated image endpoints on its current server.

`runserver` is intended for development and demonstrations. An ongoing Internet deployment needs an HTTPS reverse proxy, a production WSGI/ASGI server, `DJANGO_DEBUG=0`, a dedicated `DJANGO_SECRET_KEY`, and an explicit allowed-host list.

### Maintenance during restarts (Windows)

`deploy/nginx/nginx.conf` keeps a local proxy on **127.0.0.1:8080** in front of Django on **127.0.0.1:8000**. Point the existing HTTPS tunnel/proxy at **8080**, keeping the public URL unchanged. Requests sent directly to 8000 bypass maintenance mode. Keep Nginx and the tunnel running while restarting Django.

Waitress is included in `backend/requirements.txt` (also installed through `web/requirements.txt`). Nginx is a separate executable, not a pip package: download and extract the [official Windows mainline ZIP](https://nginx.org/en/download.html), then set `$nginx` below to its actual path.

Start Django in its own terminal, from the repository root:

```powershell
python -m pip install -r backend/requirements.txt
python backend/manage.py migrate
cd backend
waitress-serve --listen=127.0.0.1:8000 configs.wsgi:application
```

In another PowerShell terminal at the repository root, start Nginx:

```powershell
$nginx = 'C:/tools/nginx/nginx.exe' # Replace with the extracted executable's path.
$proxyRoot = (Resolve-Path deploy/nginx).Path.Replace('\', '/') + '/'
New-Item -ItemType Directory -Force deploy/nginx/run | Out-Null
& $nginx -p $proxyRoot -c nginx.conf -e stderr -t
# Continue only if the configuration test succeeds.
Start-Process -FilePath $nginx -ArgumentList "-p `"$proxyRoot`" -c nginx.conf -e stderr" -WorkingDirectory $proxyRoot -WindowStyle Hidden
```

Open **http://127.0.0.1:8080/**. From the repository root, toggle maintenance without reloading Nginx:

```powershell
New-Item -ItemType File -Force deploy/nginx/maintenance.flag | Out-Null # ON
# Stop/restart Django, then verify http://127.0.0.1:8000/api/test_reply/ directly.
Remove-Item -LiteralPath deploy/nginx/maintenance.flag # OFF after verification
```

Maintenance returns HTTP 503 with the existing Android character, wording and retry button for web requests, and `{"code":"maintenance","error":"..."}` for `/api/` requests. Already open web and Android clients show that notice above the current screen when they next receive this response. Reconnecting makes a safe GET to `/api/test_reply/`; failed POSTs are never automatically replayed. The web notice at `/maintenance/`, character and font are served directly by Nginx, even while Django is stopped. Both 503 responses have `Cache-Control: no-store` and `Retry-After: 60` (a suggested retry delay, not an estimated completion time). If Django is unreachable or the proxy times out, Nginx returns the notice automatically. Django's own error responses pass through unchanged, so an AI/speech 503 remains a feature-specific error. Rebuild/reinstall Android after updating its client code. To stop Nginx itself, use `& $nginx -p $proxyRoot -c nginx.conf -e stderr -s quit`.

For a maintenance timetable or extra notice, edit **`deploy/maintenance-message.txt`** as UTF-8 plain text. Line breaks are preserved in both web and Android notices; a blank file hides the extra message. Nginx serves it directly, so Django can remain stopped. Edits appear the next time the notice is opened or the page is refreshed, without restarting Nginx. Android needs a rebuild once for this feature; later message edits require no app update.

## 6. Files and Verification

```text
web/
  index.html            Application entry document
  assets/app.js         Desktop UI, forms, state, recording, and playback
  assets/api.js         API, session, and authenticated photo handling
  assets/icons.js       Local SVG icons
  assets/styles.css     Desktop-first responsive styles
  assets/favicon.svg    Shared grandmother/grandson family icon (embedded PNG)
  assets/todak_joy.gif   Legacy animation, retained for compatibility
  run.py                Migrations and integrated server launcher
  requirements.txt      Includes backend dependencies
  test_web.py           Web serving and API journey integration tests
  test_usability.mjs    Offline signup validation and availability regression tests
```

Web routing is implemented in `backend/configs/web.py` and `backend/configs/urls.py`. Only the explicitly allowed web assets are served, regardless of `DEBUG`. The web asset route does not expose `.env`, Python sources, the database, or upload directories. The API contract is the same one used by Android.

Run checks from the repository root. Tests use a separate temporary database and media directory, and replace external AI calls with test responses.

```powershell
python backend\manage.py check
python backend\manage.py test web
# Optional syntax checks for development environments that have Node.js installed:
node --check web\assets\app.js
node --check web\assets\api.js
node --test web\test_family_tree.mjs web\test_images.mjs web\test_usability.mjs
```

### Troubleshooting

- **Port 8000 is already in use:** Restart the existing Django server to load the web changes, or choose another port with `--port 8001`.
- **400 Bad Request / DisallowedHost:** Add the hostname or IP used to access the server to `DJANGO_ALLOWED_HOSTS` in `.env` and restart.
- **Different posts appear on Android and web:** Check that both clients use the same backend and database. The feed displays the latest 100 posts.
- **Only AI, speech, or search fails:** Check service credentials, Neo4j, and the construction worker. Secret keys do not need to be entered in the browser.
- **Recording fails:** Check localhost/HTTPS access, browser microphone permission, and the microphone connection.
- **UI changes are not visible:** Restart the backend and refresh with `Ctrl+Shift+R`.

### Family icon update — 2026-10-26

The browser favicon and the logo on login, registration and sidebar navigation share `assets/favicon.svg`. It embeds a 256 × 256 PNG resized from the same user-selected grandmother/grandson illustration used by Android, so the existing SVG asset route continues to work without backend changes. The icon URL has a version query to avoid retaining the old favicon in browser caches.

Deploy the updated `web/index.html`, `web/assets/app.js`, and `web/assets/favicon.svg` together through the project's normal server deployment. A local edit does not update the live site. Home-screen installation metadata is not configured by this change.

### Usability parity with Android — 2026-10-26

- Registration requires an exact, nonempty password confirmation. Whitespace is preserved, and validation runs before a registration request. Changing either password clears the stale validation indicator.
- Registration and password settings show requirements only in light-gray placeholders. Server-side password validators remain in force; their useful error messages are preserved.
- HTML/empty 5xx responses, network failures and timeouts display friendly availability messages with the sad boy. Existing 401 handling still expires the session. Other failures preserve the login token.
- Initial connection failure offers a manual retry; reconnecting always requests the current account and family rooms from the server. Form errors preserve drafts. POST requests are never retried automatically.
- Successful posts and text/voice comments show their own completion feedback. If a comment was saved but the following refresh fails, the UI reports that it was saved instead of inviting a duplicate submission.
- Removed the three memory-search example buttons; the free-text search form remains. Existing desktop refresh and single recording/finish controls remain available.
- Backend code, API payloads and the overall web theme are unchanged. Home-screen installation metadata is outside this change.

Offline validation from the repository root:

```sh
node --check web/assets/app.js
node --check web/assets/api.js
node --test web/test_family_tree.mjs web/test_images.mjs web/test_usability.mjs
PYTHONPATH="$PWD:$PWD/backend" python backend/manage.py test web
```

Browser validation uses a loopback-only mock API, with no production account or database writes: mismatched/matching signup, startup outage and retry, search failure and draft preservation, post failure and preserved draft, separate waiting/success states, and success feedback inside the comment dialog.

Loading artwork uses true-alpha PNGs on a transparent CSS background. The old scarf GIF is opaque and is no longer used by the current UI. The entry stylesheet and module URLs include a version query so a new deployment requests the updated character markup and styles instead of reusing a cached pre-update loading image.
