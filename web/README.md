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

1. **Sign in / register:** Use an existing Android account or create a new account. Choose a gender for family relationship labels. Passwords must contain a number and have at least 10 characters.
2. **Connect to a family room:** Create a room, or enter an invitation code and room password. When joining, select an unclaimed person in the family tree, or add parents, a spouse, and children to connect your position. Only empty positions matching your account gender can be selected. One account can belong to one room; each person can be claimed once, and multiple children of the same gender are supported. If the tree changes during joining, reload it and select your position again.
3. **Family feed:** Use the sidebar to view family posts. Click the new-post button to share text and photos. Drag photos into the upload area or select them through the file picker. Each post supports up to five photos, with limits of 10 MB per photo, 30 MB total, and 20 million source pixels per photo. Text-only posts are supported; captions are limited to 2,000 characters.
4. **Post details:** Click a photo or comment button to view photos and comments side by side. Use the thumbnails to switch photos. You can comment, generate or listen to an AI summary, and ask questions about the post. AI questions are separate from family comments, and the conversation resets when the detail dialog closes.
5. **Voice replies:** Click the microphone reply button, allow microphone access, record, and finish recording. Review and optionally correct the transcription, request an AI rewrite, and review the rewritten reply before sending it. Recordings are limited to two minutes and 5 MB. The published comment contains the converted text, not the original audio.
6. **Find memories:** Ask a natural-language question about family history. The feed's filter searches text and author names within the latest 100 loaded posts; the separate memories page searches Graphiti family records.
7. **Daily digest:** Choose a date to read or listen to its digest and open the included posts. Before the room's scheduled digest time in Korea, the digest is pending. Run the scheduler described below for automatic generation.
8. **Family / account settings:** View members, copy the invitation code, change the digest time as the room owner, or update your display name and password. Changing a password through account settings revokes tokens on other devices.

Desktop layouts use persistent sidebar navigation, a wide feed with a family information panel, and a split photo/comment dialog. Narrow screens switch to a single column. The app supports larger text, keyboard navigation, and closing dialogs with Esc.

Loading screens and pending actions display `assets/todak_joy.gif`, copied unchanged from `client/app/src/main/assets/todak/todak_joy.gif`. This includes startup, feed/detail loading, AI answers and summaries, memory search, daily digests, speech preparation, and other form requests. Pending actions show a floating status card that also remains visible inside an open dialog.

The login token is stored in the current tab's `sessionStorage`. It survives refreshes and is cleared when the tab session ends. Use the logout button to revoke it immediately on the server. Family photos are fetched with Bearer authentication and displayed through Blob URLs; tokens are never embedded in image URLs or sent to external image hosts.

## 4. AI, Speech, and Family History

Accounts, family rooms, uploads, and text comments do not require AI credentials. Other features use the existing backend and the repository-root `.env`. Do not put secret keys in web assets.

| Feature | Required configuration / process |
| --- | --- |
| Post summaries and questions; nonempty daily digests | `OPENAI_API_KEY` and the existing AI model settings |
| Listening to summaries | `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID` |
| Voice replies | `ELEVENLABS_API_KEY`, `OPENAI_API_KEY`, browser microphone permission |
| Memory search and questions requiring historical context | OpenAI configuration, running Neo4j, `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, and the family construction worker |
| Automatically generating digests at the scheduled time | A separately running `run_digest_scheduler` process |

Run family history construction and the digest scheduler in separate terminals with the same Python environment activated. To find the family room ID, sign in and inspect the `id` field in the `/api/families/current/` response in your browser's Network developer tools.

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

## 6. Files and Verification

```text
web/
  index.html            Application entry document
  assets/app.js         Desktop UI, forms, state, recording, and playback
  assets/api.js         API, session, and authenticated photo handling
  assets/icons.js       Local SVG icons
  assets/styles.css     Desktop-first responsive styles
  assets/favicon.svg    Talk Dock icon
  assets/todak_joy.gif   Shared loading animation from the Android client
  run.py                Migrations and integrated server launcher
  requirements.txt      Includes backend dependencies
  test_web.py           Web serving and API journey integration tests
```

Web routing is implemented in `backend/configs/web.py` and `backend/configs/urls.py`. Only the explicitly allowed web assets are served, regardless of `DEBUG`. The web asset route does not expose `.env`, Python sources, the database, or upload directories. The API contract is the same one used by Android.

Run checks from the repository root. Tests use a separate temporary database and media directory, and replace external AI calls with test responses.

```powershell
python backend\manage.py check
python backend\manage.py test web
# Optional syntax checks for development environments that have Node.js installed:
node --check web\assets\app.js
node --check web\assets\api.js
node --test web\test_family_tree.mjs
```

### Troubleshooting

- **Port 8000 is already in use:** Restart the existing Django server to load the web changes, or choose another port with `--port 8001`.
- **400 Bad Request / DisallowedHost:** Add the hostname or IP used to access the server to `DJANGO_ALLOWED_HOSTS` in `.env` and restart.
- **Different posts appear on Android and web:** Check that both clients use the same backend and database. The feed displays the latest 100 posts.
- **Only AI, speech, or search fails:** Check service credentials, Neo4j, and the construction worker. Secret keys do not need to be entered in the browser.
- **Recording fails:** Check localhost/HTTPS access, browser microphone permission, and the microphone connection.
- **UI changes are not visible:** Restart the backend and refresh with `Ctrl+Shift+R`.
