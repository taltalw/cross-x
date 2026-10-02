#!/usr/bin/env python3
"""Retrieve v2 knowledge requirements using the original BM25 + embeddings + RRF backend.

Reads precomputed vectors; no embedding model or LLM is loaded during retrieval.
Attach key-fact annotations to retrieved samples by domain and normalized question/answer.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / 'knowledge' / 'pipelines'))
from _offline_embeddings import EmbeddingStore
from knowledge.pipelines._knowledge_search_common import DOMAINS, read_rows, write_row
from _pipeline_common import retrieval_query_row, sample_hash, validate_v2_row

spec = importlib.util.spec_from_file_location('v2_original_retrieval', REPO_ROOT / 'knowledge/pipelines/3_retrieve_knowledge.py')
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)


def collect_annotations(paths, splits=None):
    files = []
    for path in paths:
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            # Only domain corpus files: do not ingest request_audit.jsonl or other run artifacts.
            directories = [path] if path.name in DOMAINS else [path / d for d in DOMAINS]
            for directory in directories:
                if splits:
                    files.extend(directory / f'{s}.jsonl' for s in splits if (directory / f'{s}.jsonl').is_file())
                else:
                    files.extend(sorted(directory.glob('*.jsonl')))
        else:
            raise FileNotFoundError(path)
    annotations = {}
    for path in dict.fromkeys(p.resolve() for p in files):
        for line, row in read_rows(path):
            try:
                validate_v2_row(row)
                key = (row['source_domain'], sample_hash(row['sample']))
                previous = annotations.get(key)
                if previous and previous['key_facts'] != row['key_facts']:
                    raise ValueError('conflicting key-fact annotations for the same domain and sample')
                annotations[key] = row
            except ValueError as exc:
                raise ValueError(f'{path}:{line}: {exc}') from None
    if not annotations:
        raise ValueError('no annotated domain samples found in --corpus')
    return annotations


def retrieve(row, retriever, annotations, domain_count=None):
    query_row = retrieval_query_row(row, domain_count)
    found = retriever.retrieve(query_row)
    retrieved = {}
    skipped_unannotated = {}
    for domain, candidates in found['candidates'].items():
        retrieved[domain] = []
        skipped_unannotated[domain] = []
        for candidate in candidates:
            annotation = annotations.get((domain, sample_hash(candidate['sample'])))
            if annotation is None:
                # Some provider-filtered samples may have no LLM key-fact annotation.
                # Exclude them from downstream materials while preserving an audit trail.
                skipped_unannotated[domain].append(candidate['candidate_id'])
                continue
            # Retrieve the original QA snapshot, attach annotations only after verifying QA identity.
            retrieved[domain].append({
                **candidate, 'source_domain': domain,
                'model': annotation.get('model', ''), 'key_facts': annotation['key_facts'],
                'matches': [
                    {**hit, 'required_key_fact': query_row['queries'][domain][hit['query_index'] - 1]}
                    for hit in candidate['hits']
                ],
            })
    fields = ('source_file', 'source_domain', 'model', 'sample', 'key_facts', 'fusion_domains',
              'domain_count', 'question_plan', 'answer_plans', 'required_key_facts')
    retrieval = {**found['retrieval'], 'skipped_unannotated_candidates': skipped_unannotated}
    return {**{key: row[key] for key in fields}, 'retrieved_samples': retrieved, 'retrieval': retrieval}


def process(input_file, output_file, corpus_paths, *, retriever, domain_count=None, num=None, overwrite=False):
    if input_file.resolve() == output_file.resolve():
        raise ValueError('input and output must be different files')
    if not input_file.is_file():
        raise FileNotFoundError(input_file)
    if output_file.exists() and not overwrite:
        raise FileExistsError(f'output exists: {output_file}; use --overwrite')
    if num is not None and num < 1:
        raise ValueError('num must be positive')
    annotations = collect_annotations(corpus_paths, retriever.splits)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output_file.open('w' if overwrite else 'x', encoding='utf-8') as output:
        for line, row in read_rows(input_file):
            try:
                write_row(output, retrieve(row, retriever, annotations, domain_count))
            except ValueError as exc:
                raise ValueError(f'{input_file}:{line}: {exc}; completed output retained') from None
            count += 1
            print(f'line={line} retrieved={count}', file=sys.stderr, flush=True)
            if num is not None and count >= num:
                break
    return {'processed': count, 'output': str(output_file.resolve())}


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--corpus', type=Path, nargs='+', required=True, help='Step-0 annotations for the retrieval corpus; exact QA match required')
    parser.add_argument('--atomic-root', type=Path, default=REPO_ROOT / 'knowledge/atomic')
    parser.add_argument('--embedding-root', type=Path, default=REPO_ROOT / 'knowledge/embeddings/Qwen3-Embedding-8B')
    parser.add_argument('--splits', nargs='+', choices=('train', 'dev', 'test'), help='Hybrid: require saved splits if provided; BM25 default: train')
    parser.add_argument('--method', choices=('hybrid', 'bm25'), default='hybrid')
    parser.add_argument('--domain-count', type=int, choices=range(2, 8), help='Optional check; chosen domains are read from input')
    parser.add_argument('--top-k', type=int, default=10)
    parser.add_argument('--candidate-limit', type=int, default=20)
    parser.add_argument('--rrf-k', type=int, default=60)
    parser.add_argument('--num', type=int)
    parser.add_argument('--overwrite', action='store_true')
    args = parser.parse_args()
    store = None
    try:
        if args.method == 'hybrid':
            store = EmbeddingStore(args.embedding_root, readonly=True)
        splits = args.splits if store else args.splits or ['train']
        retriever = backend.Retriever(args.atomic_root, splits, args.top_k, args.candidate_limit, args.rrf_k, store)
        report = process(args.input, args.output, args.corpus, retriever=retriever,
                         domain_count=args.domain_count, num=args.num, overwrite=args.overwrite)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1
    finally:
        if store:
            store.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
