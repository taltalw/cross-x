#!/usr/bin/env python3
"""Retrieve domain samples with BM25 + embedding cosine similarity + RRF.

Reads saved corpus and query vectors. No model loading, embedding, or API calls.
--method bm25 optionally performs lexical-only retrieval from atomic JSONL files.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import sys

import numpy as np

from _knowledge_search_common import (KNOWLEDGE_ROOT,
    base_record, output_jobs, read_rows, validate_query_row, validate_sample, write_row)
from _offline_embeddings import EmbeddingStore, digest

STOPWORDS = set("a an the of to in on at for from with and or is are was were be been being that this these those it its as by which what who how when where why do does did has have had not no answer question options select choose reply following".split())


def tokens(text):
    # Separate CJK characters; retain English/numeric scientific tokens and Greek symbols.
    return [t for t in re.findall(r"[a-z0-9]+|[\u0370-\u03ff]|[\u4e00-\u9fff]", text.casefold()) if t not in STOPWORDS]


def sample_hash(sample):
    normalized = [" ".join(sample[k].split()).casefold() for k in ("prompt", "completion")]
    return hashlib.sha256(json.dumps(normalized, ensure_ascii=False).encode()).hexdigest()


class BM25:
    def __init__(self, documents, k1=1.5, b=0.75):
        self.size, self.k1, self.b = len(documents), k1, b
        self.lengths = np.zeros(self.size, dtype=np.float64)
        postings = defaultdict(list)
        for index, document in enumerate(documents):
            terms = tokens(document)
            self.lengths[index] = len(terms)
            for term, count in Counter(terms).items():
                postings[term].append((index, count))
        self.avg = max(float(self.lengths.mean()) if self.size else 0, 1.0)
        self.postings = {term: (np.array([v[0] for v in values]), np.array([v[1] for v in values]))
                         for term, values in postings.items()}

    def search(self, query, limit):
        scores = np.zeros(self.size, dtype=np.float64)
        for term in set(tokens(query)):
            if term not in self.postings:
                continue
            ids, tf = self.postings[term]
            idf = math.log(1 + (self.size - len(ids) + 0.5) / (len(ids) + 0.5))
            scores[ids] += idf * tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * self.lengths[ids] / self.avg))
        return ranked(scores, limit, positive_only=True)


def ranked(scores, limit, positive_only=False):
    indices = np.flatnonzero(scores > 0) if positive_only else np.arange(len(scores))
    order = np.lexsort((indices, -scores[indices]))[:limit]
    return [(int(indices[i]), float(scores[indices[i]])) for i in order]


class Corpus:
    def __init__(self, domain, atomic_root, splits, offline_store=None):
        self.domain, self.rows = domain, []
        if offline_store is not None:
            self.rows, self.vectors, self.chunk_docs, self.manifest = offline_store.load_corpus(domain, splits)
            self.bm25 = BM25([r["sample"]["prompt"] + "\n" + r["sample"]["completion"] for r in self.rows])
            print(f"Loaded saved {domain}: {len(self.rows)} samples, {len(self.chunk_docs)} vectors", file=sys.stderr, flush=True)
            return
        seen = set()
        for split in splits:
            path = atomic_root / domain / f"{split}.jsonl"
            for line, sample in read_rows(path):
                validate_sample(sample)
                digest = sample_hash(sample)
                if digest in seen:
                    continue
                seen.add(digest)
                self.rows.append({"candidate_id": f"{domain}:{digest}", "source_file": str(path.resolve()),
                                  "source_line": line, "sample": {k: sample[k] for k in ("prompt", "completion")}})
        documents = [row["sample"]["prompt"] + "\n" + row["sample"]["completion"] for row in self.rows]
        self.bm25 = BM25(documents)
        self.vectors, self.chunk_docs = None, None
        print(f"Loaded {domain}: {len(self.rows)} unique samples", file=sys.stderr, flush=True)

    def semantic(self, vector, limit):
        if self.vectors is None:
            return []
        if vector.size != self.vectors.shape[1]:
            raise ValueError("query/document embedding dimension mismatch")
        scores = np.full(len(self.rows), -np.inf, dtype=np.float32)
        np.maximum.at(scores, self.chunk_docs, self.vectors @ vector)
        return ranked(scores, limit)


def fuse(rankings, limit, rrf_k):
    scores, hits = defaultdict(float), defaultdict(list)
    for query_index, method, results in rankings:
        for rank, (doc_id, score) in enumerate(results, 1):
            scores[doc_id] += 1 / (rrf_k + rank)
            hits[doc_id].append({"query_index": query_index, "method": method, "rank": rank, "score": score})
    ordered = sorted(scores, key=lambda doc_id: (-scores[doc_id], doc_id))[:limit]
    return [(doc_id, scores[doc_id], hits[doc_id]) for doc_id in ordered]


class Retriever:
    def __init__(self, atomic_root, splits=("train",), top_k=10, candidate_limit=20,
                 rrf_k=60, offline_store=None):
        if top_k < 1 or candidate_limit < 1 or rrf_k < 1:
            raise ValueError("retrieval limits must be positive")
        self.atomic_root, self.splits = atomic_root, splits
        self.offline_store = offline_store
        self.top_k, self.candidate_limit, self.rrf_k = top_k, candidate_limit, rrf_k
        self.corpora = {}

    def retrieve(self, row):
        validate_query_row(row)
        result = {}
        for domain in row["fusion_domains"]:
            if domain not in self.corpora:
                self.corpora[domain] = Corpus(domain, self.atomic_root, self.splits, self.offline_store)
            corpus = self.corpora[domain]
            queries = row["queries"][domain]
            if self.offline_store is not None and corpus.rows:
                vectors = self.offline_store.query_vectors(domain, queries)
            else:
                vectors = None
            rankings = []
            original_hash = sample_hash(row["sample"])
            for index, query in enumerate(queries, 1):
                rankings.append((index, "bm25", corpus.bm25.search(query, self.top_k + 1)))
                if vectors is not None:
                    rankings.append((index, "embedding", corpus.semantic(vectors[index - 1], self.top_k + 1)))
            # Remove a duplicate of the original A sample before ranking fusion.
            rankings = [(i, method, [(d, s) for d, s in ranks if corpus.rows[d]["candidate_id"].split(":", 1)[1] != original_hash][:self.top_k])
                        for i, method, ranks in rankings]
            result[domain] = [{**corpus.rows[d], "rrf_score": score, "hits": hits}
                              for d, score, hits in fuse(rankings, self.candidate_limit, self.rrf_k)]
        settings = {
            "method": "hybrid" if self.offline_store else "bm25", "splits": list(self.splits) if self.splits is not None else None,
            "top_k_per_query_method": self.top_k, "candidate_limit": self.candidate_limit, "rrf_k": self.rrf_k,
        }
        if self.offline_store is not None:
            config = self.offline_store.config
            settings.update(
                embedding_source="precomputed", embedding_model=config["model"],
                embedding_revision=config["revision"], embedding_config_hash=digest(config),
                embedding_root=str(self.offline_store.root.resolve()),
                max_length_tokens=config["max_length"], chunk_overlap_tokens=config["chunk_overlap_tokens"],
                query_instruction=config["query_instruction"],
                corpus_sources={d: self.corpora[d].manifest["sources"] for d in row["fusion_domains"]},
            )
            settings["splits"] = {d: sorted({s["split"] for s in self.corpora[d].manifest["sources"]}) for d in row["fusion_domains"]}
        return {**base_record(row), "candidates": result, "retrieval": settings}


def run_file(source, target, retriever, overwrite=False):
    target.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with target.open("w" if overwrite else "x", encoding="utf-8") as output:
        for line, row in read_rows(source):
            try:
                write_row(output, retriever.retrieve(row))
            except ValueError as exc:
                raise ValueError(f"{source}:{line}: {exc}; completed output retained") from None
            count += 1
            print(f"{source.name}: retrieved {count}", file=sys.stderr, flush=True)
    return {"input": str(source), "output": str(target), "rows": count}


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--input", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, help="Single input only")
    parser.add_argument("--output-root", type=Path, default=KNOWLEDGE_ROOT / "results/3_retrieve_knowledge")
    parser.add_argument("--atomic-root", type=Path, default=KNOWLEDGE_ROOT / "atomic")
    parser.add_argument("--splits", nargs="+", choices=("train", "dev", "test"), help="BM25 default: train; hybrid: use saved splits, or require an exact match")
    parser.add_argument("--method", choices=("hybrid", "bm25"), default="hybrid")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--candidate-limit", type=int, default=20)
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument("--embedding-root", type=Path, default=KNOWLEDGE_ROOT / "embeddings/Qwen3-Embedding-8B",
                        help="Existing vector directory (vectors.sqlite3); model information is read automatically")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    offline_store = None
    try:
        jobs = output_jobs(args.input, args.output, args.output_root, "3", args.overwrite)
        if args.method == "hybrid":
            offline_store = EmbeddingStore(args.embedding_root, readonly=True)
        splits = args.splits if offline_store is not None else args.splits or ["train"]
        retriever = Retriever(args.atomic_root, splits, args.top_k, args.candidate_limit, args.rrf_k, offline_store)
        for source, target in jobs:
            print(json.dumps(run_file(source, target, retriever, args.overwrite), ensure_ascii=False))
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        if offline_store is not None:
            offline_store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
