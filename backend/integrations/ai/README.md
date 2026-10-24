# Post summary and follow-up QA

Adopted prompts live in `prompts.py`. Runtime code does not import developer scripts or read ignored experiment artifacts. `post_flow.py` implements the adopted October 16 evaluation policy.

## Calls

- `GET /api/posts/<id>/message/`: basic summary from the post photo, caption, author and viewer relationship. One LLM call; no search tools or retrieval. Cached separately per viewer and prompt/configuration version. `POST` retries a failed summary.
- `POST /api/posts/<id>/questions/`: follow-up QA. The API loads the authorized family's post itself; request fields cannot override its photo, caption, author or family ID. History is client-supplied, untrusted context embedded in JSON, never system messages.

Example request (Bearer token and `Content-Type: application/json` required):

```json
{
  "question": "초록이는 뭐야?",
  "prior_dialogue": [
    {"role": "user", "text": "이 화분은 누구 거야?"},
    {"role": "assistant", "text": "지민이가 키우는 화분이에요."}
  ]
}
```

Response: `{"text": "..."}`. Responses are `no-store`. Question length: 1–1,000 characters. Optional history: at most 10 turns, each `user` or `assistant` with 1–1,000 characters of `text`. History is not persisted; clients send preceding turns on the next question. Temporary provider/search failures return HTTP 503; invalid inputs return 400/415. Authentication and family membership are required. Cross-family posts are not exposed.

QA uses C (`decomposed_5`): search decision → at most five parallel queries in one batch → answer with `tool_choice=none`. If no search is requested, it returns the first answer without retrieval. Each query retrieves five facts. Round-robin deduplication selects **five facts total**, and returns a tool output for every call, including calls receiving no selected facts. Sources are attached and deduplicated within each tool output. This preserves the evaluated policy, including its documented evidence-loss limitation; no additional retrieval loop or new ranking policy was introduced.

The Android follow-up question button/screen is not part of this backend change.

## Settings and migration

Defaults, independent of legacy STT/Digest/history and Graphiti construction settings:

```dotenv
POST_AI_MODEL=gpt-6-luna
POST_AI_SERVICE_TIER=fast
POST_AI_REASONING_EFFORT=none
```

Decision output limit: 1,200 tokens; answer output limit: 700; image detail: high; `store=False`. Service tier/model overrides are explicit operator choices; there is no automatic model fallback. The shared request worker pool still uses `GRAPHITI_SEARCH_WORKERS` (default 4); experimental concurrency 3 is not a production throughput guarantee.

WSGI/ASGI startup starts all search workers and waits for each worker to create
its Graphiti client on its own event loop, before accepting requests. Set
`OPENAI_API_KEY` and `NEO4J_PASSWORD` before starting the server; initialization
errors fail startup and close clients already initialized by other workers.
Each worker keeps one `asyncio.Runner` around its request loop and reuses its
client and loop, passing family scope and search options on each call. Requests
run sequentially within a worker; workers and the queries within a request can
run in parallel. Summaries and QA without retrieval use the prepared worker
without searching. Client construction does not prewarm network connections.
Request failures leave the worker available for the next request. On normal
process shutdown, the pool drains queued requests and closes each worker's
Graphiti/SDK clients on their owning loop before closing the loop.

Construction workers use the same initialization helper before polling posts,
then reuse their client and loop until the worker exits. Management commands
such as migrations do not start the server's search pool.

Before starting the updated backend:

```sh
.venv/bin/python backend/manage.py migrate
```

Migration `posts.0003_adaptedmessage_prompt_version` adds a cache version. Ready summaries from the old prompt regenerate on access. Failed requests still require explicit retry. An older timed-out request cannot overwrite a newer cache claim.

## Compatibility with photo uploads and profile edits

Summaries and follow-up questions receive all attached photos in upload order.
Text-only posts pass an empty image list. The summary cache version includes the
image-input policy so summaries created with only the first photo regenerate.

When integrating the photo-upload branch, keep both existing `0003` migrations.
`posts.0004_merge_post_photos_summary_cache` joins their histories without rewriting
already-applied migrations. Run `migrate` to apply any missing photo/cache schema
changes and record the merge; it also works if either `0003` is already applied.

Summary writes must still match the processing status, claim timestamp, and
prompt version. This retains protection against stale requests and profile edits
that invalidate an explanation while generation is in progress.

## Verification

From the repository root:

```sh
MOCK_AI_TESTS=1 ELEVENLABS_API_KEY= .venv/bin/python backend/manage.py test developer.test_codes.test_searching_workers developer.test_codes.test_post_qa developer.test_codes.test_searching.MemoryFlowTests developer.test_codes.test_searching.HistoryAPITests developer.test_codes.test_posts developer.test_codes.test_digests developer.test_codes.test_voice_replies
.venv/bin/python backend/manage.py makemigrations --check --dry-run
git diff --check
```

External SDKs are mocked for integration tests: API authorization and validation, server-bound family scope, actual worker/flow routing, photo/body/dialogue payloads, five tool calls, duplicate facts and empty tool outputs, shared fact budget, no-search paths, errors/client cleanup, and old-cache regeneration. No paid model call or personal-photo upload is needed. One existing live voice test is skipped with the command above.

Include the runtime modules, worker/router/provider changes, settings example, posts API and cache migration, and changed/new tests in the PR. Developer experiment folders are not required by the app. The full repository's other local experiment changes should be reviewed separately before staging.

## Known limitations

- The follow-up Android UI is a separate change; this PR provides the backend endpoint.
- A five-fact final budget can drop relevant evidence, even when search found it. The policy is kept fixed in this PR; improving ranking/coverage needs a separate measured change.
- Graphiti searches extracted facts. An original post/episode can exist without a searchable fact edge, so storage completeness does not guarantee recall.
- Search is scoped to the server-selected family, with no server-enforced historical snapshot filter. A timestamp in the prompt or query is not a guarantee that later records are excluded.
- Previous dialogue is request context, not persistent conversation storage.

## Construction descriptions

`run_construction_worker` generates a separate memory description before calling
Graphiti. `feed_description.describe_post` takes the caption, author, posting time,
and every photo from `Post.photo_files()` in order. Text-only posts use the same
path with no image inputs. This uses `OPENAI_MODEL`; displayed post summaries and
follow-up QA continue to use `POST_AI_MODEL` and the existing post flow.

`Post.images` contains the ordered storage paths; `photo_files()` returns lazy
storage references with the same `open()` boundary used by the AI flows. Apply
`posts.0006_post_images` with API/worker processes stopped to collect the previous
cover and attachments without moving the media files. The migration retains
`Post.description`, post IDs and timestamps. Graphiti still receives a text
episode named `post_<id>` in the same family group, so this storage-only upgrade
does not require re-describing posts or rebuilding existing graph episodes.

The description is cached in `Post.description`. If Graphiti storage fails, retry
reuses the description. If description generation fails, nothing is sent to
Graphiti and the post remains eligible for retry. Existing `post_<id>` episodes
are skipped; there is no backfill or regeneration of existing graph records.
