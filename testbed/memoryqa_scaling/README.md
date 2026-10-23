# MemoryQA Family Memory Scaling Evaluation

Reproduce the recorded Full History versus Graphiti comparison, or prepare a fresh run with the same inputs and memory. This is an AI evaluation package, separate from the Iteration 2 Unit/Integration suite and the other context-retrieval testbed.

## Experiment

| Item | Setting |
|---|---|
| Family | Four synthetic members: Sunhee, Doyun, Sujin, Jimin |
| Stored history | Nested 100 / 200 / 300 posts, with 40 / 80 / 120 original photos |
| Current context | The same 20 evaluation posts; photos are reshares of historical images |
| Evaluation | The same 30 questions × 3 repetitions × 3 sizes × 2 conditions = 540 tasks |
| Conditions | Full History: all frozen descriptions; Graphiti: decision → retrieval → answer |
| Generation | `gpt-6-luna`, service tier `fast`, reasoning `none`; output limits 700 / 1,200 |
| Search | Up to 5 queries; final fact budget 5; actual recorded tasks each used one query |
| Historical app | `f66961ed7201989fc1f74674afde85af88a8028f` |
| Results | Recorded on October 22, 2026; AI semantic review, independent human review pending |

Only history earlier than each question is supplied. Photos/captions and author/viewer context are shared between conditions. Historical photos are represented by frozen descriptions, not resent as a photo album. Graphiti additionally receives the app retrieval instructions. See [RESULTS.md](RESULTS.md).

## Setup

Use Python 3.12 and a clone containing the historical app commit. From the repository root:

```sh
cd testbed/memoryqa_scaling
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python memoryqa.py check
python memoryqa.py prepare-app
```

On Windows, activate with `.venv\Scripts\activate`. `prepare-app` extracts the pinned backend into ignored `.runtime/backend` from local Git history. It does not switch branches, edit the current backend, read the repository `.env`, or call a service. For a shallow clone missing this commit, fetch that history first.

## Download the 120 photos

```sh
python download_images.py
python memoryqa.py check --images
```

`image_manifest.json` pins the public MemoryQA source commit, archive object, selected ZIP entries, file sizes, destination paths, and SHA-256 hashes. The downloader requests only the selected byte ranges of the original archive, verifies CRC and SHA-256 before saving, and refuses a server response that would download the full archive. Valid local files are skipped; rerun to resume or repair corrupt files.

The 120 photos occupy 154,616,896 bytes (147.45 MiB). Actual transfer also depends on ZIP compression and request overhead. No API key or paid inference is needed. Files under `assets/images/` are ignored by Git. All input paths are relative to this package, independent of the working directory.

For a separate cache: `python download_images.py --directory PATH`, then `python memoryqa.py check --images --directory PATH`. Live evaluation uses the default `assets/images/` location.

## Recompute recorded metrics without services

```sh
python memoryqa.py verify-results
```

This checks all 540 answers against their saved answer/context hashes, validates the actual model inputs and frozen descriptions, and recomputes the six cells from raw usage, durations, and the saved semantic grades. Output is written to ignored `output/recomputed_results.json`. It does not re-grade answers or call OpenAI, Neo4j, or a judge model.

## Restore the exact memory for a new run

The graph snapshots include the recorded facts, source episodes, timestamps, UUIDs, and embeddings. Restoring them avoids nondeterministic re-extraction and paid construction. Checksums and graph contents are verified after restoration.

Use an **empty, isolated Neo4j 5.26 Community database**. Export `NEO4J_URI`, `NEO4J_USER`, and `NEO4J_PASSWORD` in the shell; scripts do not load credential files. `.env.example` lists the variables. For example, start the optional [Docker Compose service](compose.yaml):

```sh
export MEMORYQA_NEO4J_PASSWORD='choose-a-local-test-password'
docker compose -f compose.yaml up -d --wait
export NEO4J_URI='bolt://127.0.0.1:17687'
export NEO4J_USER='neo4j'
export NEO4J_PASSWORD="$MEMORYQA_NEO4J_PASSWORD"
python memoryqa.py restore-graphs --allow-db-write
python memoryqa.py check-graphs
```

Restoration refuses a nonempty database. It never clears, merges into, or repairs existing data. Stop on a partial restoration; use a fresh isolated database. Do not point restoration at a shared app database. Index construction is explicit during restoration and suppressed during QA, as in the recorded run.

Restore the three isolated SQL fixtures in separate processes:

```sh
python memoryqa.py restore-sql --size 100 --output output/reproduction/history_100
python memoryqa.py restore-sql --size 200 --output output/reproduction/history_200
python memoryqa.py restore-sql --size 300 --output output/reproduction/history_300
```

These commands create only new local SQLite databases, preserve source post IDs, reuse the verified photo files, and apply the frozen descriptions. They compare the actual app's author/viewer relationship and question payload against all 30 cases at each size. No description or graph extraction call occurs. `check-sql` with the same arguments validates an existing fixture without restoring it.

## Fresh paid evaluation

Do this only when a new paid run is intended. Export your own `OPENAI_API_KEY`, retain the restored Neo4j settings, and use the matching SQL output directories:

```sh
python memoryqa.py run --size 100 --output output/reproduction/history_100 --allow-paid
python memoryqa.py run --size 200 --output output/reproduction/history_200 --allow-paid
python memoryqa.py run --size 300 --output output/reproduction/history_300 --allow-paid
```

Without `--allow-paid`, execution stops before any model call. Every task uses the exact historical app functions and captured prompts. The adapter preserves the original task order, current image, payload, source IDs, token accounting, and timing boundaries. Completed tasks can be resumed; failures are preserved and stop execution. QA uses read-only database guards and checks the graph before and after each task.

New answers, response IDs, usage, and timing are written only to `output/`. **Saved grades apply only to the recorded answers.** Review fresh answers and final contexts against `panel/qa_gold.json` before reporting new accuracy. Sampling is nondeterministic; identical answers and latency are not guaranteed. Temperature and model sampling seed were not explicitly set. The task-order seed is 20261022.

## Files and provenance

| Path | Contents |
|---|---|
| `datasets/history_*` | Source posts, family, image metadata, and original 40-question bank. The live evaluation selects the separate 30-case panel below. |
| `panel/qa_runtime.json`, `panel/qa_gold.json` | The evaluated 30 questions, expected meanings, evidence IDs, and rubrics |
| `panel/history_*/tasks.json` | 180 ordered tasks per size; no Gold in runtime payloads |
| `snapshots/history_*` | Frozen descriptions, source IDs, original seed report, typed compressed graph |
| `snapshots/app_contract.json` | Historical app file hashes, exact prompts, settings, package versions |
| `results/history_*/results.jsonl` | All 540 recorded responses, final contexts, searches, timings, and SDK usage |
| `results/grade_index.json`, `results/*decisions.json` | Saved AI semantic judgments and hashes |
| `results/comparison.json` | Original metrics; checked against offline recomputation |
| `provenance.json`, `bundle_manifest.json` | Original/container hashes, relocation record, and distribution checksums |
| `lib/original` | Unmodified helpers from the original local execution runner; the portable adapter uses its execution and accounting functions |

The original source artifacts are untouched. Distribution changes relocate paths and reformat JSON containers; answers, Gold, prompts, descriptions, graph properties, usage, and durations are retained. Container byte hashes therefore change and are documented in `provenance.json`.

`panel/ORIGINAL-PLAN.md` and `panel/acceptance_criteria.json` are historical pre-run proposals. Their "not run" preparation status describes that original document, not this completed run. Thresholds were locally hash-frozen, not committed or independently approved before execution. Later relaxed reporting targets must not be treated as preregistered acceptance gates. AI evaluation does not replace the Iteration 2 Unit/Integration report.

## Verification and limits

Run the offline tests with `python -m unittest discover -s tests -v`. [VERIFICATION.md](VERIFICATION.md) records the packaging checks. No fresh paid answer or judge call is part of PR preparation.

This is one synthetic family with ten stories and answerable questions. Three repetitions do not create independent questions. Separate graph constructions at each size can vary in extracted facts. Report online generation input+output tokens separately from embeddings and prior ingestion cost. Timing excludes initial history assembly, ingestion, index initialization, mobile UI, and TTS.

## Source attribution

Photos are from [facebookresearch/MemoryQA](https://github.com/facebookresearch/MemoryQA), pinned at `8676e3131346be9a69a1f62bea72e752eea225f5`, under CC BY-NC 4.0. See [MEMORYQA-LICENSE.txt](MEMORYQA-LICENSE.txt). The Korean family identities, relationships, post narratives, evaluation questions, and labels are synthetic adaptations; they are not original MemoryQA ground truth or claims about the people in the photos.
