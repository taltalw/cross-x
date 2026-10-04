# Pipeline v4 — JoyRouter gt-6-as-a

Revision: `745e81f6cea45d60da0f7b449735b6a5f39e5183`. Entrypoint: `bash knowledge/pipielines_v4/run_all.sh`.
Endpoint: `https://joyrouter.jd.com/v1/chat/completions`; requested and observed model: `gt-6-as-a`.

Stages 0 and 1 are the unchanged, committed input snapshots. Stages 2, 3, and 4 were rerun from scratch. The 1,441 stage-0 annotations already exclude one input filtered during the prior v3 run; that exclusion is not counted as a new v4 provider failure.

| Stage | Input records | Output records | New provider failures | Infeasible plans |
| --- | ---: | ---: | ---: | ---: |
| 0_extract_key_facts | 1441 | 1441 | 0 | 0 |
| 1_generate_fusion_plans | 2100 | 2100 | 0 | 0 |
| 2_extract_required_key_facts | 2100 | 2100 | 0 | 0 |
| 3_retrieve_key_fact_matches | 2100 | 2100 | 0 | 0 |
| 4_generate_fusion_question | 2100 | 6255 | 4 | 11 |

The original stage functions, prompts, validators, and order were retained. Stage 2 used 16 workers. Stage 4 began with 16 workers and continued with 32. Runs resumed from durable checkpoints after schema errors and a process interruption. Retry feedback was clarified for the original infeasible-plan schema and exact source citations, including literal Unicode and codepoint diagnostics. No citation was substituted or normalized locally. Output order and validated response/row checkpoints were retained. See execution_history, job summaries, and worker_config.json for execution settings.
Stage 2 generated short retrieval keywords. Stage 3 used the original hybrid retrieval backend, top-k 10 and at most 10 candidates per fusion domain. Stage 4 selected exact evidence and revised the plan and requirements to fit that evidence before generating easy/medium/hard variants.
Explicit provider filters/refusals were recorded and skipped. Infeasible plans are reported separately. No partial difficulty triplet is emitted when a provider refusal interrupts generation.
See rejected_samples.jsonl and screened_out_samples.jsonl for source positions and decisions.

API settings: temperature 1, reasoning effort low, up to 5 attempts. Token limits start at repository defaults; length-truncated responses retry with a larger limit up to 8,192. Schema retries include the previous response and validation feedback; exact source-reference validators remain enforced.
The existing isolated pipielines_v3/.env environment was reused because its pinned requirements exactly match v4. Qwen3-Embedding-8B used local weights on GPU 7; v4 has its own vector store at /pfs/ydy/wyt/cross-x/knowledge/embeddings/v4-test-Qwen3-Embedding-8B.
Validation: 17 repository tests and 9 execution tests passed; real GPU encoding passed. Final checks cover preserved seed/source hashes, all stage-2/4 checkpoints, ordered outputs, retrieved corpus identities, revised plans, exact evidence references, complete difficulty triplets, endpoint/model audit, and vector-store integrity.
These checks do not independently establish factual correctness of every generated question.

The archive contains all stage JSONL files, run manifests, audits, execution utilities, tests, and environment reports. It omits credentials, model weights, Python environment, response/row caches, and the vector database.
