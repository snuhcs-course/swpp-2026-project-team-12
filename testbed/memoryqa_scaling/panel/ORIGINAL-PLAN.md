# Family Memory QA Evaluation Plan

## Purpose and status

Compare the app's Graphiti memory retrieval with Full History as the same family's stored history grows. Measure whether the app answers family questions correctly, obtains supporting facts, and reduces generation tokens without excessive response time.

Status: offline preparation only. No paid calls, database connections, graph mutations, or new answers are part of this preparation. The shared app and prior experiment artifacts remain unchanged. Acceptance targets below are proposals for agreement before the next run; the previous ten-question results were already known.

This plan revises the previous ten-question, five-repeat comparison to **30 distinct questions and three repeats**. The former plan and results remain in their original directory. More questions expand fact coverage; three repeats measure response variability. Repetition does not create additional independent questions.

## Dataset and cases

| Item | Definition |
|---|---|
| Family | Same four people: Sunhee, Doyun, Sujin, and Jimin; frozen app author/viewer relations |
| History sizes | 100 / 200 / 300 posts, with 40 / 80 / 120 unique historical photos |
| History nesting | 100 is a subset of 200, which is a subset of 300; shared posts are identical |
| Current posts | Same 20 evaluation posts and their photos; these are current context, not additional stored history |
| Questions | FQ01–FQ10 inherited unchanged; FQ11–FQ30 added; three distinct attributes per event thread |
| Gold | Expected meaning, sufficient alternative source sets, interpretation rules, and confusable or outdated sources |
| Question time | Each case's explicit `asked_at`; only history created strictly before it is eligible |
| Scope | Answerable family-memory questions; single facts, changed facts, corrections, identity separation, and explicit past states |

Question wording, current post, viewer, and question time of the inherited ten cases are preserved exactly. All existing Gold fields, including expected answers and source alternatives, are preserved. A grading clarification for FQ05 separates raw source support from facts surviving in the generated memory description: M05-4 or M05-6 supports the gift-giver in the source posts, but M05-6's frozen description can blur giving versus delivery. Retrieving that ID alone must not automatically pass semantic Evidence Coverage. Old results are not regraded.

Every selected source exists at all three sizes. The 100 common posts and their frozen descriptions are identical across scales. Additional histories were reviewed for competing entities and later changes; the added stories are distinct and do not revise the selected answers. `evidence_review.json` contains 90 case-by-scale reviews with original captions and the actual stored descriptions. Gold follows explicit source statements, not imagined photo identities or later events.

The added histories primarily precede the core October storyline. This scaling comparison increases competing memory volume while retaining the same target facts; it does not test newly changing Gold at each scale or represent 30 independent families. Many requested attributes have one sufficient source. Multi-hop reasoning and refusal behavior need a separate panel if evaluated later.

## Conditions and common settings

| Setting | Both conditions |
|---|---|
| Answer model | `gpt-6-luna` |
| Service tier / reasoning | `fast` / `none` |
| Answer / decision token limits | 700 / 1200 |
| Search question limit / fact budget | 5 / 5 in Graphiti; no search in Full History |
| Image detail | `high`; same current photo and caption |
| Prior conversation | Empty per task; no answer cache or previous answer reuse |
| Concurrency / seed | 1 / 20261022 for task ordering; no claim of deterministic API outputs |
| Timeout / SDK retries | 60 seconds / at most 1 SDK retry |
| Warmup | No request is removed as warmup |
| Source app commit | `f66961ed7201989fc1f74674afde85af88a8028f` |

**Full History:** one final-answer call receives every eligible frozen photo-plus-caption description, including author, source post ID, and timestamp. Historical original images are not resent as a photo album. The final-answer instruction is the same detailed `POST_QA` instruction used by the app.

**Graphiti:** the app's search-decision instruction generates up to five questions; the existing graph search supplies the budgeted facts and source descriptions; the same final-answer instruction answers using the current photo, caption, and retrieved context. Use the existing isolated experiment groups and the exact same description snapshot as Full History. Do not rebuild or repair memory for this comparison.

`frozen_sources.json` records the actual prompt strings, package versions, app settings, source signatures, description hashes, and existing graph seed reports. Those are historical seed reports, not a new live graph verification. Model alias resolution must be recorded from actual responses at execution time.

## Execution design

| History size | Full History | Graphiti | Total |
|---|---:|---:|---:|
| 100 | 30 questions × 3 = 90 | 30 questions × 3 = 90 | 180 |
| 200 | 90 | 90 | 180 |
| 300 | 90 | 90 | 180 |
| Total | 270 | 270 | **540 tasks** |

The same 30 questions, Gold, photos, viewers, and time cutoffs are used in all six cells. Within each repeat, shuffle question blocks and the two conditions with the fixed ordering seed. Execute sizes 100, 200, and 300 sequentially. Report the ordering because server load and caching can vary over time. A task is a user question, not one API request: Graphiti adds search-decision and search-related calls, so the total number of API requests can exceed 540.

Before a future paid run:

1. Review the 30 cases and the proposed thresholds with the team; retain named human reviews only when actually completed. The current review is AI semantic review.
2. Commit the panel, Gold, criteria, task manifests, and prompt/source hashes. They are local files now; no commit or submission is claimed.
3. Obtain explicit authorization to execute the new 540-task experiment. Earlier experiment approvals do not initiate this one.
4. Revalidate the source/app locks, SQL mapping, existing graph group contents, graph fingerprints, and image hashes. Stop on drift; preserve the frozen comparison rather than silently using a newer app.
5. Use an isolated experiment adapter to consume this panel's manifests and the unchanged app execution functions. The prior ten-case dispatcher and the original 20-case main command do **not** select this new panel. No paid execution adapter has been activated in this preparation.
6. Save every task result, actual final memory context, searches, supplied source IDs, usage, response IDs, returned model/settings, stage timings, and errors. Preserve failed attempts and all prior results.

No new description generation or graph construction is planned. Construction costs already incurred are reported separately if comparing total lifecycle cost. Their exclusion from online QA must not be presented as zero construction cost.

## Grading and metrics

Grade semantic meaning using `qa_gold.json`, not exact-string matching. A response can satisfy the requested fact and still fail strict accuracy because of an unsupported extra claim. A correct guess without sufficient supplied context can satisfy the answer metric and fail Evidence Coverage. Abstention on these answerable questions fails accuracy but is not automatically a false connection.

| Metric | Definition |
|---|---|
| Answer Satisfaction | Requested fact correct for the intended entity and time / 90 planned responses per cell |
| Answer Accuracy | Requested fact correct with no material false or unsupported factual additions / 90 |
| Evidence Coverage | Actual final memory context contains sufficient support / 90; check meaning after extraction and budgeting |
| Source Post Coverage | Final context includes every ID in at least one declared sufficient source set / 90; diagnostic, not proof of factual support |
| False Connection Rate | Responses asserting a wrong entity, relation, object, or temporal state / 90 |
| Unsupported Addition Rate | Responses with at least one material false or unsupported addition / 90 |
| Memory Update Error Rate | Responses asserting an old state as current / responses in the declared update subset |
| Generation Tokens per Question | All observed generation input plus output tokens across decision, answer, and internal generation calls / planned tasks |
| Embedding Tokens per Question | Observed search embedding tokens / planned tasks; keep separate from generation tokens |
| Generation Tokens per Correct Answer | Same total generation tokens / strict correct responses; undefined if none are correct |
| Mean Response Time | Mean of all measured task durations, retaining first requests, SDK retries, and errors |
| P95 Response Time | Nearest-rank P95; sorted duration at position 86 of 90 |
| Per Question Repeat Consistency | Correct counts 0/3, 1/3, 2/3, or 3/3; show all repetitions |

The update subset is **FQ04, FQ05, FQ06, FQ07, FQ08, FQ09, FQ10, FQ11, FQ13, FQ15, FQ17**: 11 questions × 3 = 33 responses per cell. The subset is diagnostic; no post-result case selection is allowed. FQ03, FQ24, and FQ30 explicitly ask about earlier facts and must not be relabeled as requests for the current state.

“Generation tokens” means **input plus output**, not output tokens alone. Report input, output, cached input, and embedding tokens separately. Cached input still counts in the token totals; do not infer dollar cost from raw token counts. Aggregate the complete workflow, not just the Graphiti final-answer call. Missing usage makes token-dependent metrics unavailable until resolved.

Latency follows the existing execution function's timer: from prepared task execution through decision, search, answer, retries, and client cleanup. It excludes earlier history-payload assembly, ingestion, and mobile UI/upload/TTS time. Record decision/search/answer times as diagnostics. This is server-side QA time, not end-to-end app latency.

AI grading must retain answer-specific reasons and source snippets. Mask condition and scale labels during semantic answer grading where possible. Manually review every failure and a fixed first ten cases by ID in every cell, including all three repeats. Keep human status pending until a person actually signs. Ambiguous labels should be discussed with the course staff before formal submission; any Gold correction after new results requires a new version and explicit erratum.

## Proposed acceptance criteria

Apply the same criteria **separately at each size and for each condition**. Passing one size or averaging the six cells does not hide a failure at another size.

| Metric | Proposed target | Count per 90-response cell |
|---|---:|---:|
| Answer Satisfaction | ≥90% | ≥81 correct |
| Evidence Coverage | ≥90% | ≥81 sufficiently supported |
| Answer Accuracy | ≥85% | ≥77 correct without unsupported additions |
| False Connection Rate | ≤5% | ≤4 affected responses |
| Unsupported Addition Rate | ≤5% | ≤4 affected responses |
| P95 Response Time | ≤10 seconds | Position 86 ≤10 seconds; separate interaction target |

The five quality targets define quality acceptance. The latency target is a proposed product target, not a course requirement, and is reported separately. A 5% limit allows four errors out of 90, not five. Team agreement is pending; these are not claims that the app currently passes.

For validity, require exactly 540 unique planned task records, zero future-record leakage, zero Gold leakage, and zero app/input drift. Preserve system errors in the planned denominators as failed answers. An interrupted run is incomplete, not a pass. Do not silently rerun semantic failures or report only the best of three responses.

## Relative comparison and reporting

At each history size report Graphiti divided by Full History for generation tokens per question and mean latency; Full History is 1.00. Report accuracy and Evidence Coverage as percentages plus **percentage-point differences**, so a token saving cannot conceal a quality loss. Also show tokens per strict correct answer.

Relative efficiency metrics have no mandatory superiority threshold. The experiment may show a trade-off. Report prior construction/description cost separately and, if complete cost data exist, show amortized setup-plus-QA cost without mixing it with online-only token totals.

Each condition-size cell contains 30 question clusters, not 90 independent questions. Show the three repeat results and per-question counts. For exploratory uncertainty, use paired bootstrap intervals over the 30 question IDs, retaining all repeats of a selected question together and pairing both conditions. Do not claim equivalence or non-inferiority from an interval that includes zero. The same ten stories and known prior results limit generalization beyond this family.

The final result report should include: six-cell metrics and pass/fail against these original targets; relative charts; per-question repeat counts; failures with actual answer, expected meaning, final context, and source IDs; and stage diagnoses distinguishing source-description omission, graph extraction, retrieval/budgeting, and answer generation. Post Summary, injection resistance, unanswerable questions, and independent identity/relationship recognition are outside this 540-task comparison.

## Results

**Not run.** No accuracy, token, latency, or pass/fail results have been generated for this panel. Existing ten-case results are development evidence and will not be reused as new responses.
