# 七领域 test 语料向量

[run_3.sh](run_3.sh) 同时准备七领域完整 test 语料向量、步骤 2 的查询向量，并执行检索：

```bash
bash knowledge/pipielines_v3/run_3.sh
```

脚本复用 `knowledge/pipelines/embed_knowledge.py --kind corpus`，语料是原始问答的 `prompt` 和 `completion`。查询向量由 v3 的 `embed_required_key_facts.py` 写入同一个向量库。默认库为 `knowledge/embeddings/v3-test-Qwen3-Embedding-8B`，已有兼容向量会复用缓存。

向量阶段默认使用本地 `.env`，未安装时使用本机现有 `crossx` 环境；设备自动选择 CUDA 或 CPU。可设置 `EMBEDDING_PYTHON_BIN`、`GPU_ID`、`EMBEDDING_DEVICE`、`EMBEDDING_BATCH_SIZE`、`EMBEDDING_ROOT`；完整配置见[运行说明](run_serial.md)。
