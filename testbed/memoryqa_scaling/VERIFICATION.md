# Reproduction Preparation Verification

Prepared on October 23, 2026, against `iteration-2-demo` at `044d7d5`. The recorded evaluation uses the isolated historical backend `f66961ed7201989fc1f74674afde85af88a8028f`.

| Check | Result |
|---|---|
| Public image download | 120/120 downloaded by the new script; CRC, SHA-256, file size, and image decoding passed |
| Cold transfer | 153,637,378 range-response bytes; the 3,119,085,326-byte full ZIP was not downloaded |
| Warm cache | 120/120 reused; zero network requests and zero transfer bytes |
| Dataset | Nested 100/200/300 histories, 40/80/120 photos, 20 current posts, 30 common questions; evidence and time cutoffs valid at every size |
| App extraction | All 71 recorded backend file hashes match the pinned commit |
| Dependencies | Clean Python 3.12 environment installed all 31 pinned packages from public PyPI |
| Automated checks | 15 passed, including download failure/cache handling, tamper detection, typed graph round trips, and both app QA paths with mock services |
| SQL fixtures | 120/220/320 posts restored; authors, family slots, timestamps, descriptions and 90 question payloads match the app |
| Graph snapshots | Three original groups exported through read transactions; fingerprints match the recorded run |
| Graph restoration | Fresh Neo4j 5.26 Community instance restored 171/311/439 nodes and 313/554/786 edges with exact typed properties and embeddings |
| Search indexes | Required full-text indexes ONLINE; nonempty-database restoration refused without changes |
| Result recomputation | All six 90-response cells reproduce the saved correctness, evidence, error counts, token totals and mean/P95 durations |
| Source preservation | 77 original source files checked unchanged; current shared app source untouched |
| Fresh paid evaluation | Not executed; no new description, extraction, answer, or judge call |

Machine-readable checks are in [verification/](verification/). Raw answers and semantic judgments are in [results/](results/). Downloaded photos, extracted app sources, new SQL fixtures, and generated reports stay in ignored directories.

The paid-run command is opt-in and produces new responses requiring new semantic review. Its service credentials, current API availability, and future response quality have not been tested with paid calls. Recorded AI grading has not received independent human signoff. Post-run reporting targets are not pre-run acceptance gates.
