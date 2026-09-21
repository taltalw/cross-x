#!/usr/bin/env python3
"""Run the original pipeline and retain response metadata without credentials."""

import datetime
import io
import json
import os
from pathlib import Path
import runpy
import sys
import urllib.request


original_urlopen = urllib.request.urlopen
audit_path = Path(os.environ["REQUEST_AUDIT_PATH"])


def audited_urlopen(request, *args, **kwargs):
    with original_urlopen(request, *args, **kwargs) as response:
        raw = response.read()
        status = response.status
        final_url = response.geturl()
    body = json.loads(raw)
    payload = json.loads(request.data) if request.data else {}
    record = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "url": final_url,
        "status": status,
        "requested_model": payload.get("model"),
        "response_model": body.get("model"),
        "response_id": body.get("id"),
        "usage": body.get("usage"),
        "finish_reasons": [choice.get("finish_reason") for choice in body.get("choices", [])],
    }
    with audit_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    return io.BytesIO(raw)


urllib.request.urlopen = audited_urlopen
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name="__main__")
