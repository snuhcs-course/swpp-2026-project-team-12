Title: test: package Post QA and family history search experiments
Base: iteration-3-demo

Packages the Iteration 3 search experiments for review and reproduction without changing application code.

- Post QA: original, interleaved, reranked, and separate fact/episode selection; includes the fixed-selection prompt comparison.
- Family History Search: Full History vs. Graphiti on 100/200/300 historical posts, 30 questions, three repetitions (540 answers).
- Includes frozen cases, prompts/selectors, saved answers and grades, compact expected metrics, and an offline verifier. Generated reports are excluded from Git; report scripts remain available.
- Keeps photos, database snapshots, credentials, and environments out of Git. Checksummed external input bundles are required for live reruns and must be provided separately.

Validation: offline metrics matched the original result baselines; all three Post QA selectors matched archived selections; 300 request hashes verified; 25 tests passed. Read-only Neo4j checks passed at all three sizes with no paid API calls. Fresh dependency installation and graph restoration were not rerun.

From the repository root:

```sh
python3 -B testbed/search_experiments/verify.py
```

See `testbed/search_experiments/README.md` for setup and paid-run gates. Original grading caveats and measurement boundaries are retained.
