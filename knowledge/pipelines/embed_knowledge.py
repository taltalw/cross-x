#!/usr/bin/env python3
"""Precompute Qwen3 corpus or retrieval-query embeddings from JSONL paths.

--kind corpus: an atomic root, a domain directory, or JSONL files.
--kind queries: stage-2 JSONL files or directories (including multiple groups).
Both kinds use the SAME --embedding-root. Retrieval then needs no model or API.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys

from _knowledge_search_common import DOMAINS, KNOWLEDGE_ROOT, read_rows, validate_query_row
from _offline_embeddings import DEFAULT_MODEL, DEFAULT_INSTRUCTION, EmbeddingStore, LocalQwenEncoder

DEFAULT_EMBEDDING_ROOT = KNOWLEDGE_ROOT / "embeddings/Qwen3-Embedding-8B"


def corpus_inputs(inputs, splits, domain=None):
    groups = {}
    for path in inputs:
        if path.is_file():
            name = domain or path.parent.name
            paths = [path]
            if name not in DOMAINS:
                raise ValueError(f"cannot infer domain of {path}; pass --domain")
            groups.setdefault(name, []).extend(paths)
        elif path.is_dir():
            if domain or path.name in DOMAINS:
                name = domain or path.name
                groups.setdefault(name, []).extend(path / f"{split}.jsonl" for split in splits)
            else:
                for name in DOMAINS:
                    if (path / name).is_dir():
                        groups.setdefault(name, []).extend(path / name / f"{split}.jsonl" for split in splits)
        else:
            raise FileNotFoundError(path)
    if not groups:
        raise ValueError("no domain corpus found in --input")
    for name, paths in groups.items():
        groups[name] = list(dict.fromkeys(p.resolve() for p in paths))
        for path in groups[name]:
            if not path.is_file() or path.suffix != ".jsonl":
                raise FileNotFoundError(f"expected a JSONL corpus: {path}")
    return groups


def query_inputs(inputs):
    paths = []
    for path in inputs:
        if path.is_file() and path.suffix == ".jsonl":
            paths.append(path.resolve())
        elif path.is_dir():
            found = sorted(p.resolve() for p in path.glob("*.jsonl") if p.is_file())
            if not found:
                raise ValueError(f"no JSONL files in {path}")
            paths.extend(found)
        else:
            raise ValueError(f"expected query JSONL or directory: {path}")
    pairs = []
    for path in dict.fromkeys(paths):
        for line, row in read_rows(path):
            try:
                validate_query_row(row)
            except ValueError as exc:
                raise ValueError(f"{path}:{line}: {exc}") from None
            pairs.extend((domain, query) for domain in row["fusion_domains"] for query in row["queries"][domain])
    return list(dict.fromkeys(pairs))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, nargs="+", required=True)
    parser.add_argument("--kind", choices=("corpus", "queries"), required=True)
    parser.add_argument("--domain", choices=DOMAINS, help="For a corpus file whose parent is not its domain")
    parser.add_argument("--splits", nargs="+", choices=("train", "dev", "test"), default=["train"])
    parser.add_argument("--embedding-root", type=Path, default=DEFAULT_EMBEDDING_ROOT)
    parser.add_argument("--model", help=f"Default: existing store model, or {DEFAULT_MODEL}; accepts a local model path")
    parser.add_argument("--revision", help="Model commit/tag; existing store revision is reused by default")
    parser.add_argument("--device", default="auto", help="auto, cpu, cuda, cuda:0, ...")
    parser.add_argument("--dtype", choices=("auto", "float32", "float16", "bfloat16"), default=None)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--max-length", type=int, default=None, help="Token budget per document chunk (default 2048)")
    parser.add_argument("--chunk-overlap", type=int, default=None, help="Overlap tokens (default 128)")
    parser.add_argument("--query-instruction", default=None)
    parser.add_argument("--local-files-only", action="store_true", help="Never download model files")
    parser.add_argument("--replace-corpus", action="store_true", help="Atomically replace a changed domain corpus; cached vectors remain reusable")
    args = parser.parse_args()
    store = None
    try:
        if args.batch_size < 1:
            raise ValueError("batch-size must be positive")
        if args.kind == "queries" and args.domain:
            raise ValueError("--domain is only used for corpus inputs")
        groups = corpus_inputs(args.input, args.splits, args.domain) if args.kind == "corpus" else None
        pairs = query_inputs(args.input) if args.kind == "queries" else None
        existing = {}
        if (args.embedding_root / "vectors.sqlite3").exists():
            old = EmbeddingStore(args.embedding_root, readonly=True)
            existing = old.config
            old.close()
        model = args.model or existing.get("model", DEFAULT_MODEL)
        encoder = LocalQwenEncoder(
            model, args.revision or existing.get("revision"), args.device,
            args.dtype or existing.get("dtype", "auto"),
            args.max_length if args.max_length is not None else existing.get("max_length", 2048),
            args.chunk_overlap if args.chunk_overlap is not None else existing.get("chunk_overlap_tokens", 128),
            args.query_instruction if args.query_instruction is not None else existing.get("query_instruction", DEFAULT_INSTRUCTION),
            args.local_files_only,
        )
        store = EmbeddingStore(args.embedding_root, encoder.config)
        if args.kind == "corpus":
            for domain, paths in groups.items():
                report = store.build_corpus(domain, paths, encoder, args.batch_size, args.replace_corpus)
                print(json.dumps(report, ensure_ascii=False), flush=True)
        else:
            print(json.dumps(store.build_queries(pairs, encoder, args.batch_size)), flush=True)
    except (OSError, ValueError, RuntimeError, sqlite3.Error, ImportError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        if store is not None:
            store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
