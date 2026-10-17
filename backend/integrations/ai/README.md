# Post summary and follow-up QA

Adopted prompts live in `prompts.py`. Runtime code does not import developer scripts or read ignored experiment artifacts. `post_flow.py` implements the adopted October 16 evaluation policy.

## Calls

- `GET /api/posts/<id>/message/`: basic summary from the post photo, caption, author and viewer relationship. One LLM call; no search tools or Graphiti client. Cached separately per viewer and prompt/configuration version. `POST` retries a failed summary.
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

QA uses C (`decomposed_5`): search decision → at most five parallel queries in one batch → answer with `tool_choice=none`. If no search is requested, it returns the first answer without creating Graphiti. Each query retrieves five facts. Round-robin deduplication selects **five facts total**, and returns a tool output for every call, including calls receiving no selected facts. Sources are attached and deduplicated within each tool output. This preserves the evaluated policy, including its documented evidence-loss limitation; no additional retrieval loop or new ranking policy was introduced.

The Android follow-up question button/screen is not part of this backend change.

## Settings and migration

Defaults, independent of legacy STT/Digest/history and Graphiti construction settings:

```dotenv
POST_AI_MODEL=gpt-6-luna
POST_AI_SERVICE_TIER=fast
POST_AI_REASONING_EFFORT=none
```

Decision output limit: 1,200 tokens; answer output limit: 700; image detail: high; `store=False`. Service tier/model overrides are explicit operator choices; there is no automatic model fallback. The shared request worker pool still uses `GRAPHITI_SEARCH_WORKERS` (default 4); experimental concurrency 3 is not a production throughput guarantee.

Before starting the updated backend:

```sh
.venv/bin/python backend/manage.py migrate
```

Migration `posts.0003_adaptedmessage_prompt_version` adds a cache version. Ready summaries from the old prompt regenerate on access. Failed requests still require explicit retry. An older timed-out request cannot overwrite a newer cache claim.

## Verification

From the repository root:

```sh
MOCK_AI_TESTS=1 ELEVENLABS_API_KEY= .venv/bin/python backend/manage.py test developer.test_codes.test_post_qa developer.test_codes.test_searching.MemoryFlowTests developer.test_codes.test_searching.HistoryAPITests developer.test_codes.test_posts developer.test_codes.test_digests developer.test_codes.test_voice_replies
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
