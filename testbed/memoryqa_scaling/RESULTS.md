# Family Memory QA Scaling Results

Completed 540 fresh tasks: 30 questions × 3 repeats × 3 history sizes × Full History/Graphiti. The shared app, prompts, frozen descriptions, SQL records, and existing graph groups were preserved. Actual generation responses used gpt-6-luna, fast service tier, and no reasoning effort.

| History | Condition | Answer Satisfaction | Strict Answer Accuracy | Evidence Coverage | Generation tokens/question | Mean seconds | P95 seconds |
|---:|---|---:|---:|---:|---:|---:|---:|
| 100 | full_history | 90/90 | 84/90 | 90/90 | 16,617.5 | 2.81 | 4.05 |
| 100 | graphiti | 67/90 | 66/90 | 69/90 | 9,762.1 | 5.49 | 7.86 |
| 200 | full_history | 90/90 | 83/90 | 90/90 | 29,208.4 | 3.01 | 4.31 |
| 200 | graphiti | 70/90 | 70/90 | 70/90 | 9,748.9 | 5.44 | 7.30 |
| 300 | full_history | 87/90 | 84/90 | 90/90 | 41,658.8 | 3.04 | 4.19 |
| 300 | graphiti | 68/90 | 66/90 | 70/90 | 9,771.9 | 5.51 | 7.39 |

Generation tokens include all observed workflow input and output, not only final answers. Embeddings and prior construction costs are reported separately. No first requests were removed as warmup. The same frozen photo-plus-caption descriptions formed the memory source for both conditions; current images and captions were shared. Graphiti uses the app retrieval instructions in addition to the common base answer prompt.

Graphiti reduced generation tokens per question by 41.3%, 66.6%, and 76.5%, while mean latency was 1.95, 1.81, and 1.81 times Full History. Cached input is included in token counts; these are not dollar-cost reduction estimates.

Of 65 Graphiti core-answer misses, 42 had no fact-edge attribution for a sufficient Gold source set, 18 lacked sufficient raw retrieval despite source attribution, and five failed despite sufficient final context. No final-budget source loss was observed. All 270 Graphiti tasks generated one search query, so multi-query splitting was not tested here. Full History missed the father-book question in all three 300-post trials; the image showed the mother's book rather than the father's recorded Blue Exorcist.

Automatic index initialization is suppressed by the private read-only harness. Reported QA latency excludes that initialization workload and is not full app latency.

Report token and latency ratios with Full History set to 1.00, alongside percentage-point quality differences. Do not infer a speed advantage from fewer tokens. The raw result files contain actual per-call usage and decision/search/answer durations.

All 30 cases were answerable. Three repetitions are repeated measurements of the same questions, not 90 independent questions per cell. This single synthetic family and known prior cases limit generalization. Paired bootstrap intervals cluster by question and are exploratory. The three existing graphs were constructed separately: shared descriptions are identical, but extracted facts can differ, so cross-scale accuracy differences are not a pure effect of history size.

AI semantic review was used, with exact-answer and context hashes. Independent human review, team agreement, and pre-run Git commit were not completed. Proposed thresholds were hash-frozen locally before calls and were not changed after results; they are not represented as formally approved course acceptance gates.


Detailed recorded outputs: `results/history_*/results.jsonl`; grades: `results/grade_index.json`; metrics: `results/comparison.json`.
