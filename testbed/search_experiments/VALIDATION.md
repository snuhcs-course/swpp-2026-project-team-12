# Package verification — 2026-11-06

- Base: `iteration-3-demo` / `ed296d4f6c86d4b2b6da48273d5e525e98bd641d`.
- Shared application changes: none. All additions are under `testbed/search_experiments/`.
- Paid calls during PR preparation: 0. Existing answers and grades were preserved.
- Offline recomputation: Family History 540 answers; Post QA selection 300 answers; prompt candidate 100 answers. Published accuracy, evidence recall, tokens, and timings matched.
- Actual selector replay: original, interleave, and pinned fact-5/episode-5 outputs matched all 100 archived candidate sets.
- Request checks: 200 original/interleave request hashes and 100 prompt-comparison request hashes matched. Only the intended fields change.
- Existing tests: Post QA 20/20; Family History 5/5.
- Real read-only Neo4j compatibility: 100/200/300 histories passed using Graphiti 0.31.1 and the frozen graph. Query embeddings were mocked locally; no paid request was made.
- Packaging checks: syntax, SHA-256 manifests, no embedded image payloads/API keys/absolute home-directory paths in PR contents. Archives use lossless XZ compression.
- Clean-folder verification: recorded result recomputation works without external inputs, API keys, Neo4j, application imports, or installed third-party Python packages.

## Limits

A fresh dependency installation, fresh Neo4j restore, and new paid answer generation were not performed during packaging. Existing graph connectivity was checked. For an exact live replay, the two external input bundles in `artifacts.json` must be supplied separately; they are not hosted at a public URL. The available account must support the original model/tier.

The original judge limitations remain. In particular, Family History's automated memory-update-error result must not be treated as proof of zero stale answers. See the grading caveats in README.md. New report generation checks portable source hashes instead of the original developer's local checkouts.

## Report cleanup — 2026-11-06

Generated report files are excluded from Git. The verifier uses compact expected Post QA metrics extracted unchanged from the original results; Family History uses the archived metrics. Raw answer archives and grading criteria are unchanged. Offline recomputation, 20 Post QA tests, and 5 Family History contract tests passed after cleanup. No paid calls were made.
