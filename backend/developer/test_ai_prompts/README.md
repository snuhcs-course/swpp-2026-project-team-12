# Feed description prompt

The production prompt is `DESCRIPTION_INSTRUCTIONS` in
`backend/integrations/ai/feed_description.py`. It describes the caption and all ordered post photos
before graph construction, without retrieving existing graph memories.

Run offline request/response tests (no API calls):

```bash
python3 backend/manage.py test developer.test_ai_prompts developer.test_codes.test_searching.HistoryAPITests developer.test_codes.test_post_migration_compat
```

Apply migrations before running construction. The merge migration joins the
already-applied `0003_post_description` branch with
`0004_merge_post_photos_summary_cache`; existing descriptions, attachments, and
summary cache versions are preserved:

```bash
python3 backend/manage.py migrate
python3 backend/manage.py run_construction_worker --family-id 1 --once
```

The worker uses the `SUMMARY_AI_*` model group and `OPENAI_API_KEY` for memory
descriptions, the same group as displayed summaries; follow-up QA uses `ANSWER_AI_*`. `Post.photo_files()` provides the cover followed by ordered extra
photos; text-only posts send no images. The worker prefetches attachments and
the description adapter reads ORM relations and files outside the event loop. It caches a successful
description on `Post.description`, then stores it in Graphiti. Failed descriptions
are retried without falling back to the caption; Graphiti failures reuse the cache.
Existing graph episodes are skipped. Video is not yet supported by the feed model.

To evaluate prompt quality, use a new post with an image and caption, run the worker,
and inspect `Post.description`. This invokes paid OpenAI and Graphiti calls.
Check coverage of visible details and legible text, fidelity to caption facts and
plans, and whether observations are clearly distinguished from caption claims.
