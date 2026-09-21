#!/usr/bin/env python3
"""Precompute v2 required-key-fact vectors in the original Qwen embedding store.

Uses the original embed_knowledge CLI and model/configuration checks.
Only --kind queries is supported; build atomic corpus vectors with the original script.
"""
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / 'knowledge/pipelines'))
import embed_knowledge as original
from knowledge.pipelines._knowledge_search_common import read_rows
from _pipeline_common import retrieval_query_row


def query_inputs(inputs):
    paths = []
    for path in inputs:
        if path.is_file():
            paths.append(path)
        elif path.is_dir():
            paths.extend(sorted(path.rglob('*.jsonl')))
        else:
            raise FileNotFoundError(path)
    if not paths:
        raise ValueError('no step-2 JSONL files in --input')
    pairs = []
    for path in dict.fromkeys(p.resolve() for p in paths):
        for line, row in read_rows(path):
            try:
                query = retrieval_query_row(row)
            except ValueError as exc:
                raise ValueError(f'{path}:{line}: {exc}') from None
            pairs.extend((domain, phrase) for domain, phrases in query['queries'].items() for phrase in phrases)
    return list(dict.fromkeys(pairs))


def reject_corpus(*args, **kwargs):
    raise ValueError('v2 helper supports --kind queries only; build corpus vectors with knowledge/pipelines/embed_knowledge.py')


def main():
    # Adapt only input reading; original encoder and store behavior remain intact.
    old_queries, old_corpus = original.query_inputs, original.corpus_inputs
    try:
        original.query_inputs, original.corpus_inputs = query_inputs, reject_corpus
        return original.main()
    finally:
        original.query_inputs, original.corpus_inputs = old_queries, old_corpus


if __name__ == '__main__':
    raise SystemExit(main())
