"""Local Qwen3 embedding encoder and a durable store consumed by retrieval.

Only LocalQwenEncoder imports torch/transformers; reading saved vectors needs NumPy.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys

import numpy as np

from _knowledge_search_common import nonempty, read_rows, validate_sample

DEFAULT_MODEL = "Qwen/Qwen3-Embedding-8B"
DEFAULT_INSTRUCTION = (
    "Given a knowledge requirement, retrieve question-answer samples that provide "
    "the domain concepts, mechanisms, rules, or methods needed to satisfy it."
)
FORMAT_VERSION = 1


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def normalized_sample_id(sample):
    # Matches stage 3's existing sample_hash, preserving candidate IDs.
    return digest([" ".join(sample[k].split()).casefold() for k in ("prompt", "completion")])


def file_hash(path):
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(part)
    return checksum.hexdigest()


def token_windows(ids, size, overlap):
    if size < 1 or not 0 <= overlap < size:
        raise ValueError("chunk overlap must be smaller than the token budget")
    for start in range(0, len(ids), size - overlap):
        yield ids[start:start + size]
        if start + size >= len(ids):
            break


def last_token_pool(hidden, mask):
    """Select the actual last unmasked token, regardless of padding direction."""
    import torch
    positions = torch.arange(mask.shape[1], device=mask.device).expand_as(mask)
    last = positions.masked_fill(mask == 0, -1).max(dim=1).values
    if (last < 0).any():
        raise ValueError("cannot pool an empty sequence")
    return hidden[torch.arange(hidden.shape[0], device=hidden.device), last]


class LocalQwenEncoder:
    def __init__(self, model=DEFAULT_MODEL, revision=None, device="auto", dtype="auto",
                 max_length=2048, overlap=128, instruction=DEFAULT_INSTRUCTION, local_files_only=False):
        if max_length < 32 or not 0 <= overlap < max_length:
            raise ValueError("max-length must be >=32 and overlap in [0, max-length)")
        nonempty(instruction, "query instruction")
        try:
            import torch
            from transformers import AutoConfig, AutoModel, AutoTokenizer
            import transformers
            from packaging.version import Version
            if Version(transformers.__version__) < Version("4.51.0"):
                raise ImportError("transformers>=4.51.0 required for Qwen3")
        except ImportError as exc:
            raise RuntimeError("Install the embedding environment described in EMBEDDING.md: " + str(exc)) from None
        self.torch = torch
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        if device.startswith("cuda") and not torch.cuda.is_available():
            raise ValueError("CUDA is unavailable; select --device cpu or repair the GPU environment")
        if dtype == "auto":
            dtype = "float32" if device == "cpu" else "float16"
        if device == "cpu" and dtype == "float16":
            raise ValueError("use --dtype float32 on CPU")
        self.device, self.max_length, self.overlap = device, max_length, overlap
        self.instruction = instruction
        kwargs = {"revision": revision, "local_files_only": local_files_only, "trust_remote_code": False}
        config = AutoConfig.from_pretrained(model, **kwargs)
        if config.model_type != "qwen3":
            raise ValueError("this encoder uses Qwen3 last-token pooling; select a Qwen3-Embedding model")
        if max_length > config.max_position_embeddings:
            raise ValueError("max-length exceeds the model context limit")
        resolved = getattr(config, "_commit_hash", None)
        if resolved:
            kwargs["revision"] = resolved
        self.tokenizer = AutoTokenizer.from_pretrained(model, padding_side="left", **kwargs)
        self.special_tokens = self.tokenizer.num_special_tokens_to_add(pair=False)
        if overlap >= max_length - self.special_tokens:
            raise ValueError("overlap leaves no document content budget")
        self.model = AutoModel.from_pretrained(model, torch_dtype=getattr(torch, dtype), **kwargs).to(device).eval()
        self.model.config.use_cache = False
        self.dimension = int(config.hidden_size)
        # Pin downloaded revisions; detect changes to weights/tokenizer in local directories.
        local_path = Path(model)
        local_identity = None
        if local_path.is_dir():
            local_identity = digest([(str(p.relative_to(local_path)), p.stat().st_size, p.stat().st_mtime_ns)
                                     for p in sorted(local_path.rglob("*")) if p.is_file() and p.suffix in (".json", ".safetensors", ".bin")])
            model = str(local_path.resolve())
        self.config = {
            "format_version": FORMAT_VERSION, "model": model, "revision": resolved or revision,
            "local_model_identity": local_identity, "dimension": self.dimension, "dtype": dtype,
            "max_length": max_length, "chunk_overlap_tokens": overlap, "query_instruction": instruction,
            "pooling": "last_non_padding_token", "normalize": True,
            "document_text": "prompt + newline + completion", "transformers_version": transformers.__version__,
            "tokenizer_hash": digest(self.tokenizer.backend_tokenizer.to_str()),
        }
        print(f"Embedding model={model} device={device} dtype={dtype} dimension={self.dimension}", file=sys.stderr, flush=True)

    def document_sequences(self, text):
        ids = self.tokenizer.encode(text, add_special_tokens=False, truncation=False)
        if not ids:
            raise ValueError("document has no tokens")
        budget = self.max_length - self.special_tokens
        return [self.tokenizer.build_inputs_with_special_tokens(part) for part in token_windows(ids, budget, self.overlap)]

    def query_sequence(self, domain, query):
        # Official Qwen3 embedding format: queries have an instruction; documents do not.
        text = f"Instruct: {self.instruction} Target domain: {domain}.\nQuery:{query}"
        ids = self.tokenizer.encode(text, add_special_tokens=True, truncation=False)
        if len(ids) > self.max_length:
            raise ValueError("query plus instruction exceeds --max-length; query was not truncated")
        return ids

    def encode_sequences(self, sequences):
        if not sequences or any(not ids or len(ids) > self.max_length for ids in sequences):
            raise ValueError("empty or overlong embedding input")
        batch = self.tokenizer.pad([{"input_ids": ids, "attention_mask": [1] * len(ids)} for ids in sequences],
                                   padding=True, return_tensors="pt").to(self.device)
        with self.torch.inference_mode():
            output = self.model(**batch, use_cache=False)
            pooled = last_token_pool(output.last_hidden_state, batch["attention_mask"]).float()
            vectors = self.torch.nn.functional.normalize(pooled, p=2, dim=1)
        return vectors.cpu().numpy()


class EmbeddingStore:
    """One model/configuration per directory; corpus and query vectors share that space."""
    def __init__(self, root, config=None, readonly=False):
        self.root, self.readonly = Path(root), readonly
        path = self.root / "vectors.sqlite3"
        if readonly:
            if not path.is_file():
                raise FileNotFoundError(f"missing embedding store: {path}; run embed_knowledge.py first")
            self.db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=60)
        else:
            self.root.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(path, timeout=60)
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS vectors (key TEXT PRIMARY KEY, value BLOB NOT NULL);
                CREATE TABLE IF NOT EXISTS corpora (domain TEXT PRIMARY KEY, manifest TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS documents (domain TEXT, doc_index INTEGER, record TEXT NOT NULL, PRIMARY KEY(domain,doc_index));
                CREATE TABLE IF NOT EXISTS chunks (domain TEXT, chunk_index INTEGER, doc_index INTEGER, vector_key TEXT NOT NULL, PRIMARY KEY(domain,chunk_index));
                CREATE TABLE IF NOT EXISTS queries (domain TEXT, query TEXT, vector_key TEXT NOT NULL, PRIMARY KEY(domain,query));
            """)
        found = self.db.execute("SELECT value FROM metadata WHERE key='config'").fetchone()
        if found is None:
            if readonly or config is None:
                self.db.close()
                raise ValueError("embedding store has no model configuration")
            with self.db:
                self.db.execute("INSERT INTO metadata VALUES ('config',?)", (json.dumps(config, sort_keys=True),))
            self.config = config
        else:
            self.config = json.loads(found[0])
            if config is not None and self.config != config:
                self.db.close()
                raise ValueError("embedding model/settings differ from this store; select a new --embedding-root")
        if self.config.get("format_version") != FORMAT_VERSION:
            self.db.close()
            raise ValueError("unsupported embedding store version")
        if not readonly:
            temp = self.root / f".metadata-{os.getpid()}.json"
            temp.write_text(json.dumps(self.config, ensure_ascii=False, indent=2) + "\n")
            os.replace(temp, self.root / "metadata.json")

    def close(self):
        self.db.close()

    def unpack(self, value):
        vector = np.frombuffer(value, dtype=np.float32).copy()
        if vector.size != self.config["dimension"] or not np.isfinite(vector).all() or not np.isclose(np.linalg.norm(vector), 1, atol=1e-4):
            raise ValueError("corrupt or incompatible saved vector")
        return vector

    def cache_sequences(self, sequences, encoder, batch_size):
        keys = [digest(ids) for ids in sequences]
        pending = {}
        for key, ids in zip(keys, sequences):
            if key not in pending and self.db.execute("SELECT 1 FROM vectors WHERE key=?", (key,)).fetchone() is None:
                pending[key] = ids
        todo = list(pending)
        for offset in range(0, len(todo), batch_size):
            batch = todo[offset:offset + batch_size]
            matrix = np.asarray(encoder.encode_sequences([pending[key] for key in batch]), dtype=np.float32)
            if matrix.shape != (len(batch), self.config["dimension"]) or not np.isfinite(matrix).all():
                raise ValueError("encoder returned invalid vector dimensions or values")
            norms = np.linalg.norm(matrix, axis=1, keepdims=True)
            if (norms <= 0).any() or not np.isfinite(norms).all():
                raise ValueError("encoder returned invalid vector norms")
            matrix = matrix / norms
            with self.db:
                self.db.executemany("INSERT OR IGNORE INTO vectors VALUES (?,?)", [(key, v.tobytes()) for key, v in zip(batch, matrix)])
        return keys, len(pending)

    def build_corpus(self, domain, paths, encoder, batch_size=8, replace=False):
        if batch_size < 1:
            raise ValueError("batch-size must be positive")
        sources = [{"path": str(p.resolve()), "sha256": file_hash(p), "split": p.stem} for p in paths]
        found = self.db.execute("SELECT manifest FROM corpora WHERE domain=?", (domain,)).fetchone()
        if found:
            manifest = json.loads(found[0])
            if manifest["sources"] == sources:
                return {"domain": domain, "status": "cached", **manifest}
            if not replace:
                raise ValueError(f"{domain} corpus has different sources/content; use --replace-corpus or a new embedding root")
        rows, mappings, seen = [], [], set()
        pending_sequences, pending_documents = [], []
        new_vectors = 0

        def flush():
            nonlocal new_vectors
            keys, encoded = self.cache_sequences(pending_sequences, encoder, batch_size)
            new_vectors += encoded
            mappings.extend(zip(pending_documents, keys))
            pending_sequences.clear()
            pending_documents.clear()

        for path in paths:
            for line, sample in read_rows(path):
                validate_sample(sample)
                sample_id = normalized_sample_id(sample)
                if sample_id in seen:
                    continue
                seen.add(sample_id)
                doc_index = len(rows)
                rows.append({"candidate_id": f"{domain}:{sample_id}", "source_file": str(path.resolve()),
                             "source_line": line, "sample": {k: sample[k] for k in ("prompt", "completion")}})
                sequences = encoder.document_sequences(sample["prompt"] + "\n" + sample["completion"])
                for sequence in sequences:
                    pending_sequences.append(sequence)
                    pending_documents.append(doc_index)
                    if len(pending_sequences) >= batch_size:
                        flush()
                if len(rows) % 500 == 0:
                    print(f"{domain}: {len(rows)} samples, {len(mappings)} chunks", file=sys.stderr, flush=True)
        if pending_sequences:
            flush()
        # Detect a file edited while indexing, rather than publishing a mixed snapshot.
        if any(file_hash(Path(s["path"])) != s["sha256"] for s in sources):
            raise ValueError("corpus changed during embedding; rerun after source edits finish")
        manifest = {"sources": sources, "samples": len(rows), "chunks": len(mappings),
                    "model_config_hash": digest(self.config)}
        # Publish the complete corpus atomically; interrupted runs leave vector cache reusable.
        with self.db:
            self.db.execute("DELETE FROM documents WHERE domain=?", (domain,))
            self.db.execute("DELETE FROM chunks WHERE domain=?", (domain,))
            self.db.executemany("INSERT INTO documents VALUES (?,?,?)", [(domain, i, json.dumps(row, ensure_ascii=False)) for i, row in enumerate(rows)])
            self.db.executemany("INSERT INTO chunks VALUES (?,?,?,?)", [(domain, i, doc, key) for i, (doc, key) in enumerate(mappings)])
            self.db.execute("INSERT OR REPLACE INTO corpora VALUES (?,?)", (domain, json.dumps(manifest)))
        return {"domain": domain, "status": "built", "new_vectors": new_vectors, **manifest}

    def build_queries(self, pairs, encoder, batch_size=8):
        if batch_size < 1:
            raise ValueError("batch-size must be positive")
        pairs = list(dict.fromkeys(pairs))
        pending = [(d, q) for d, q in pairs if self.db.execute("SELECT 1 FROM queries WHERE domain=? AND query=?", (d, q)).fetchone() is None]
        for offset in range(0, len(pending), batch_size):
            batch = pending[offset:offset + batch_size]
            keys, _ = self.cache_sequences([encoder.query_sequence(d, q) for d, q in batch], encoder, batch_size)
            with self.db:
                self.db.executemany("INSERT OR REPLACE INTO queries VALUES (?,?,?)", [(d, q, key) for (d, q), key in zip(batch, keys)])
            print(f"Queries embedded: {min(offset + len(batch), len(pending))}/{len(pending)}", file=sys.stderr, flush=True)
        return {"queries": len(pairs), "new_queries": len(pending)}

    def load_corpus(self, domain, splits=None):
        found = self.db.execute("SELECT manifest FROM corpora WHERE domain=?", (domain,)).fetchone()
        if not found:
            raise ValueError(f"no saved corpus for {domain}; run embed_knowledge.py --kind corpus first")
        manifest = json.loads(found[0])
        if manifest["model_config_hash"] != digest(self.config):
            raise ValueError("corpus uses a different embedding model configuration")
        actual_splits = {s["split"] for s in manifest["sources"]}
        if splits is not None and set(splits) != actual_splits:
            raise ValueError(f"requested splits {splits} do not match saved {domain} corpus {sorted(actual_splits)}")
        rows = [json.loads(v[0]) for v in self.db.execute("SELECT record FROM documents WHERE domain=? ORDER BY doc_index", (domain,))]
        joined = self.db.execute("SELECT c.doc_index,v.value FROM chunks c JOIN vectors v ON c.vector_key=v.key WHERE c.domain=? ORDER BY c.chunk_index", (domain,))
        vectors, docs = [], []
        for doc, value in joined:
            if not 0 <= doc < len(rows):
                raise ValueError("invalid saved chunk-to-document mapping")
            docs.append(doc)
            vectors.append(self.unpack(value))
        if len(rows) != manifest["samples"] or len(vectors) != manifest["chunks"] or set(docs) != set(range(len(rows))):
            raise ValueError("incomplete saved corpus; rebuild embeddings")
        matrix = np.stack(vectors) if vectors else np.empty((0, self.config["dimension"]), dtype=np.float32)
        return rows, matrix, np.asarray(docs, dtype=np.int64), manifest

    def query_vectors(self, domain, queries):
        values = []
        for query in queries:
            found = self.db.execute("SELECT v.value FROM queries q JOIN vectors v ON q.vector_key=v.key WHERE q.domain=? AND q.query=?", (domain, query)).fetchone()
            if found is None:
                raise ValueError(f"missing saved query embedding for {domain}: {query!r}; run embed_knowledge.py --kind queries on this input first")
            values.append(self.unpack(found[0]))
        return np.stack(values)
