"""Shared IO, validation, and HTTP helpers for retrieval and filtering."""

from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DOMAINS = ("medical", "legal", "financial", "mathematics", "computer_science", "geography", "chemistry")
KNOWLEDGE_ROOT = Path(__file__).resolve().parents[1]


class APIError(RuntimeError):
    pass


def nonempty(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")
    return value


def read_rows(path: Path):
    with path.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except ValueError as exc:
                raise ValueError(f"{path}:{number}: invalid JSON") from exc
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{number}: expected a JSON object")
            yield number, value


def validate_sample(sample: Any) -> None:
    if not isinstance(sample, dict):
        raise ValueError("sample must be an object")
    for field in ("prompt", "completion"):
        nonempty(sample.get(field), f"sample.{field}")


def validate_query_row(row: dict) -> None:
    source = row.get("source_domain")
    if not isinstance(source, str) or source not in DOMAINS:
        raise ValueError("unsupported source_domain")
    validate_sample(row.get("sample"))
    nonempty(row.get("fusion_idea"), "fusion_idea")
    domains = row.get("fusion_domains")
    if not isinstance(domains, list) or not domains:
        raise ValueError("fusion_domains must be a nonempty list")
    if any(not isinstance(d, str) or d not in DOMAINS or d == source for d in domains):
        raise ValueError("invalid fusion domain")
    if len(set(domains)) != len(domains):
        raise ValueError("duplicate fusion domain")
    queries = row.get("queries")
    if not isinstance(queries, dict) or set(queries) != set(domains):
        raise ValueError("queries must cover exactly the fusion domains")
    for domain, values in queries.items():
        if not isinstance(values, list) or len(values) != 3:
            raise ValueError(f"{domain} requires three queries")
        for value in values:
            nonempty(value, "query")
        if len({" ".join(v.split()).casefold() for v in values}) != 3:
            raise ValueError(f"duplicate queries for {domain}")


def base_record(row: dict) -> dict:
    return {key: row[key] for key in ("source_domain", "sample", "fusion_domains", "fusion_idea", "queries")}


def output_jobs(inputs: list[Path], output: Path | None, output_root: Path, prefix: str, overwrite: bool):
    if not inputs:
        raise ValueError("at least one input file is required")
    if output is not None and len(inputs) != 1:
        raise ValueError("--output requires exactly one input")
    jobs = [(p, output if output is not None else output_root / f"{prefix}_{p.name}") for p in inputs]
    source_paths = {p.resolve() for p in inputs}
    targets = [p.resolve() for _, p in jobs]
    if len(set(targets)) != len(targets) or source_paths.intersection(targets):
        raise ValueError("output paths collide with each other or with input files")
    for source, target in jobs:
        if not source.is_file():
            raise FileNotFoundError(source)
        if target.exists() and not overwrite:
            raise FileExistsError(f"output exists: {target}; use --overwrite to replace")
    return jobs


def write_row(stream, row: dict):
    stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
    stream.flush()


class JSONAPI:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 180, retries: int = 2):
        for name, value in (("API base URL", base_url), ("API key", api_key), ("model", model)):
            nonempty(value, name)
        if not base_url.startswith(("https://", "http://")):
            raise ValueError("API base URL must start with http:// or https://")
        if not math.isfinite(timeout) or timeout <= 0 or retries < 0:
            raise ValueError("invalid API timeout or retries")
        self.base_url, self.api_key, self.model = base_url.rstrip("/"), api_key, model
        self.timeout, self.retries = timeout, retries

    def request(self, route: str, payload: dict, validate):
        error = "request failed"
        for attempt in range(self.retries + 1):
            request = urllib.request.Request(
                self.base_url + route,
                data=json.dumps({"model": self.model, **payload}, ensure_ascii=False).encode(),
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return validate(json.load(response))
            except urllib.error.HTTPError as exc:
                error = f"HTTP {exc.code}"
                exc.close()
                if exc.code not in (408, 409, 429) and exc.code < 500:
                    raise APIError(error) from None
            except (urllib.error.URLError, TimeoutError, OSError):
                error = "connection failed or timed out"
            except (ValueError, KeyError, TypeError, IndexError):
                error = "response failed JSON/schema validation"
            if attempt < self.retries:
                time.sleep(min(2 ** attempt, 8))
        raise APIError(f"{error} after {self.retries + 1} attempts")

    def chat(self, system: str, data: dict, validate, max_tokens: int):
        def parse(body):
            return validate(json.loads(body["choices"][0]["message"]["content"]))
        return self.request("/chat/completions", {
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": json.dumps(data, ensure_ascii=False)}],
            "temperature": 0, "max_tokens": max_tokens, "response_format": {"type": "json_object"},
        }, parse)
