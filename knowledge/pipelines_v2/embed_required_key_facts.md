# v2 required key facts 向量准备

`embed_required_key_facts.py` 将步骤 2 每个所选领域的三个 `key_fact` 转成 `(domain, query)`，复用原版 `embed_knowledge.py` 的本地 Qwen 编码器、配置校验和向量缓存。辅助入口只接受 `--kind queries`。语料向量仍用原版脚本生成。

七领域完整 test 语料可直接运行 `bash knowledge/pipelines_v2/run_embed_test_corpus.sh`，默认 GPU 1，写入同一个 v2 test 向量库。见 [语料向量说明](embed_test_corpus.md)。

```bash
/mnt/data1/wangyatong/anaconda3/envs/crossx/bin/python \
  knowledge/pipelines_v2/embed_required_key_facts.py --kind queries \
  --input run_012_joyrouter_20260922/2_extract_required_key_facts \
  --embedding-root knowledge/embeddings/v2-test-Qwen3-Embedding-8B
# 等价包装入口：
bash knowledge/pipelines_v2/run_embed_required_key_facts.sh
```

包装脚本默认读取 `cross-x/run_012_joyrouter_20260922` 中的步骤 2 结果，使用 `crossx` Python 环境，向量写入 `knowledge/embeddings/v2-test-Qwen3-Embedding-8B`。可通过 `V2_ROOT`、`INPUT_ROOT`、`EMBEDDING_ROOT`、`PYTHON_BIN` 环境变量覆盖。此入口仅生成需求向量；后续语料向量和检索也应使用同一个向量库。

包装脚本默认只使用物理 GPU 1（`GPU_ID=1`）。通过 `CUDA_VISIBLE_DEVICES` 限定可见设备后，程序中的 `cuda:0` 对应物理 GPU 1。可用 `GPU_ID` 切换显卡；包装入口固定传入 `--device cuda:0`。

需要原版 embedding 环境（NumPy、PyTorch、transformers 等，见 `knowledge/pipelines/EMBEDDING.md`）。已有库自动复用模型和配置；新的库默认使用 Qwen/Qwen3-Embedding-8B。可传原版 `--device`、`--dtype`、`--batch-size`、`--local-files-only` 等参数。该步骤会实际加载模型，步骤 3 本身只读已保存向量。

输入目录递归读取步骤 2 JSONL，不应传混有其他阶段文件的目录。对重复 `(domain, query)` 去重，已缓存 query 不重复编码。模型和分块等配置冲突时原版存储层拒绝混用。
