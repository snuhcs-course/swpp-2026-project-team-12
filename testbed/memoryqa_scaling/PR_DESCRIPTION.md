## Changes

- Add the MemoryQA-based four-person family evaluation with 100/200/300 history posts and a common 30-question panel.
- Download the selected 120 public photos from a pinned source, with size, CRC and SHA-256 checks. Photos are excluded from Git.
- Include frozen descriptions and graph snapshots so memory can be restored without new extraction calls.
- Preserve the 540 recorded responses, semantic grades, usage and timings, with an offline metric verification command.
- Use the historical app commit in an isolated runtime. Current app code and the existing testbeds are unchanged.

## Validation

- Clean Python 3.12 installation of 31 pinned dependencies; 15 automated checks passed.
- Downloaded all 120 photos and verified their hashes; a second run reused all files without network access.
- Restored all three SQL fixtures and checked 90 app question payloads.
- Restored all three graph snapshots into a separate Neo4j 5.26 database; properties, embeddings and search indexes verified.
- Recomputed all six result cells from the saved responses and grades.
- Repeated offline checks, tests and SQL restoration from a fresh clone in a different path containing spaces.
- No new paid model or judge calls. Fresh responses require separate grading.
