# v2 run 0 — JoyRouter results

- Commit: `22b45a54a874ce2d7261977ad1d2412628fd8c80`
- API base URL: `https://joyrouter.jd.com/v1`
- API route: `/chat/completions`
- Requested model and all recorded response model fields: `gt-6-as-a`
- Dataset: first 10 nonblank samples from each of 7 atomic `test.jsonl` files (70 total).
- Status: completed; exit code 0; elapsed 955.45 seconds.
- Settings: temperature 1, reasoning effort low, max tokens 4096, timeout 180 seconds, 2 retries.
- Validation: all 70 records passed source correspondence, metadata, and key-fact structure checks. All 70 recorded successful responses reported HTTP 200 and finish reason `stop`.
- TLS certificate verification remained enabled. The process used the environment's network proxy with the exact JoyRouter HTTPS API URL.
- Pipeline source files were not modified. Existing local source changes were preserved.
- Credentials were supplied in memory and are absent from the result files.

Each `<domain>/test.jsonl` preserves the original sample and adds 2–3 `key_facts`.
See `run.log`, `run_manifest.json`, `request_audit.jsonl`, and `validation.json` for execution details.
The audit records successful responses and their token usage; failed requests and any usage they incurred are not included in those totals.
These checks verify structure and provenance, not factual correctness of every generated phrase.

To repeat generation, supply the key through an environment variable and choose a new output directory:

```bash
API_BASE_URL=https://joyrouter.jd.com/v1 \
API_KEY="$JOYROUTER_API_KEY" \
MODEL=gt-6-as-a API_TEMPERATURE=1 API_REASONING_EFFORT=low \
NUM=10 ATOMIC_SPLIT=test OUTPUT_ROOT=/path/to/new/output \
PYTHONDONTWRITEBYTECODE=1 \
bash knowledge/pipelines_v2/run_0_extract_key_facts.sh \
  --max-tokens 4096 --timeout 180 --retries 2
```

The optional `_runtime/audited_python.py` launcher used in this run only records response metadata. It does not alter prompts or model parameters.
