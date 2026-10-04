"""Verify the isolated environment and actual GPU embedding before paid work."""
import importlib.metadata
import json
import os
from pathlib import Path
import sys

RUNTIME = Path(__file__).resolve().parent
V4 = RUNTIME.parents[1]
REPO = V4.parents[1]
os.environ['CUDA_VISIBLE_DEVICES'] = '7'
os.environ['OMP_NUM_THREADS'] = '4'
os.environ['TOKENIZERS_PARALLELISM'] = 'false'
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / 'knowledge/pipelines'))

import numpy as np
import torch
from knowledge.pipelines._offline_embeddings import LocalQwenEncoder

assert Path(sys.prefix).resolve() == (REPO / 'knowledge/pipielines_v3/.env').resolve()
assert (V4 / 'requirements-crossx.txt').read_bytes() == (REPO / 'knowledge/pipielines_v3/requirements-crossx.txt').read_bytes()
versions = {name: importlib.metadata.version(name) for name in
            ('numpy', 'torch', 'transformers', 'safetensors', 'packaging', 'huggingface-hub', 'tokenizers')}
assert torch.cuda.is_available(), 'CUDA unavailable in v4 environment'
print('Loading local Qwen3-Embedding-8B on GPU 7', flush=True)
encoder = LocalQwenEncoder('/pfs/models/Qwen3-Embedding-8B', device='cuda', local_files_only=True)
sequences = [encoder.document_sequences('A circle has area pi times its radius squared.')[0],
             encoder.query_sequence('mathematics', 'circle area')]
vectors = encoder.encode_sequences(sequences)
assert vectors.shape == (2, 4096)
assert np.isfinite(vectors).all()
assert np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-4)
report = {'passed': True, 'python': sys.executable, 'prefix': sys.prefix, 'versions': versions,
          'gpu_id': 7, 'gpu_name': torch.cuda.get_device_name(), 'embedding_model': encoder.config,
          'embedding_test_shape': list(vectors.shape),
          'peak_gpu_allocated_bytes': torch.cuda.max_memory_allocated()}
(RUNTIME / 'preflight.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({key: report[key] for key in ('passed', 'versions', 'gpu_name', 'embedding_test_shape')}, ensure_ascii=False))
