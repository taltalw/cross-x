# Step 4 fusion questions — 2026-09-30

Completed: 210 questions in 21 JSONL files. Each of seven source domains has
10 questions for each total domain count (2, 3, 4), or 30 questions per source.

Input: `../3_retrieve_key_fact_matches/<source>/test_domain_count_<count>.jsonl`.
Output: `<source>/test_domain_count_<count>.jsonl` in this directory.
All 210 inputs match the corresponding step 2 records from
`pipelines_v2/outputs/run_012_joyrouter_20260922`.

The existing `knowledge/pipelines_v2/4_generate_fusion_question.py` was run
without modifications, using JoyRouter `https://joyrouter.jd.com/v1` and
requested/observed model `gt-6-as-a`. Settings: temperature 1, reasoning effort
low, 4096 maximum output tokens, 8 concurrent groups, 180-second request timeout,
and up to 4 retries. Full batch: 10:35:02–10:56:35 UTC on 2026-09-30.

Each record preserves the original sample, key facts, fusion domains, plans,
required key facts, complete retrieved candidates, and retrieval provenance.
Generated fields include the English question, A–D options, correct answer,
explanation, distractor analyses, used material IDs, and plan adjustment.

All 21 groups passed validation: record counts and order, preservation of input
fields, domain counts, four distinct options, three distinct wrong-option
analyses, and valid material references covering every additional domain.
The inputs and stage script remained unchanged during execution. No inputs were
skipped. These checks do not establish factual correctness, unique solvability,
or whether every participating domain is substantively necessary. The results
have not undergone a separate factual review.

Local run files: `../_runtime/run4_20260930/`. This includes `run.py`,
`run_manifest.json`, `summary.json`, `validation.json`, `request_audit.jsonl`,
individual logs, and validated-response caches. No credentials are stored there.

Archive: `../cross-x_v2_step4_gt-6-as-a_20260930.zip`. It contains these 21 JSONL
files, this README, the summary and validation reports, and the run manifest.
