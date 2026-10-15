# TODO

- Evaluate retrieval quality for post summary, STT correction, and digest with feature-specific examples.

All four features are connected to `integrations.ai.flow.answer_with_memory`.
`provider.adapt`, `rewrite`, and `summarize` use the 3-way flow; family history uses
the 2-way flow. Feature prompts stay in `integrations.ai.provider`, and the server
binds the family scope in `searching_workers`.
