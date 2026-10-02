# v3 运行入口

在 `cross-x` 目录首次安装环境：

```bash
bash knowledge/pipielines_v3/install_env.sh
```

已有本机 `crossx` 环境时可跳过安装。设置 `API_BASE_URL`、`API_KEY`、`MODEL` 后运行：

```bash
bash knowledge/pipielines_v3/run_all.sh
```

总入口依次执行 [run_0.sh](run_0.sh)、[run_1.sh](run_1.sh)、[run_2.sh](run_2.sh)、[run_3.sh](run_3.sh)、[run_4.sh](run_4.sh)。各阶段也能单独运行，例如已有步骤 0–2 的结果时只运行 `bash knowledge/pipielines_v3/run_3.sh`。`run_all.sh` 在启动前检查全部原始输入、目标 JSONL 和 Python 依赖，避免付费 API 调用后才发现环境不完整。

| 步骤 | 输入 | 输出与行为 |
| --- | --- | --- |
| 0 | 七领域 `knowledge/atomic/<domain>/test.jsonl` | 全量标注，写入 `0_extract_key_facts/<domain>/test.jsonl` |
| 1 | 步骤 0 | 每个源领域 × 总领域数 2、3、4 各生成一组方案，`NUM` 默认每组 10 条 |
| 2 | 步骤 1 | 消费全部方案，为每个新增领域提取三个知识需求 |
| 3 | 原始问答、步骤 0 和步骤 2 | 先用同一向量库编码原始语料和需求查询，再运行 BM25 + 向量混合检索 |
| 4 | 步骤 3 | 筛选检索证据；通过方案各生成 `easy`、`medium`、`hard` 三条，未通过的不生成 |

步骤 1–4 的文件路径为 `<stage>/<source>/test_domain_count_<N>.jsonl`，其中 `N` 包含源领域。全部输出默认位于 `V3_ROOT=knowledge/pipielines_v3/outputs`。`NUM=all` 仅使步骤 1 处理所有有效输入；步骤 0 本来全量执行，步骤 2–4 不另行限量。

配置集中在 [run_config.sh](run_config.sh)。Python 默认优先选用 `knowledge/pipielines_v3/.env/bin/python`，其次使用本机现有 `crossx` 环境。设备默认 `auto`，有可用 CUDA 时用所选 GPU，否则用 CPU；CPU 上运行 8B 模型可能很慢。可在运行前通过环境变量覆盖 `V3_ROOT`、`ATOMIC_ROOT`、`PYTHON_BIN`、`EMBEDDING_PYTHON_BIN`、`EMBEDDING_ROOT`、`GPU_ID`、`EMBEDDING_DEVICE`、`EMBEDDING_MODEL`、`EMBEDDING_DTYPE`、`EMBEDDING_BATCH_SIZE`、`TOP_K` 和 `CANDIDATE_LIMIT`。默认向量库为 `knowledge/embeddings/v3-test-Qwen3-Embedding-8B`，与 v2 分开；兼容的已有向量会复用缓存。首次使用会读取或下载 Qwen3-Embedding-8B 权重。

五个步骤及总入口只接受 `--overwrite`。不传时，目标 JSONL 已存在就会在该阶段发起请求前报错；传入后从头重写对应阶段，而非断点续跑。步骤 3 的 `--overwrite` 只用于检索 JSONL，不会清空向量库。全部重跑示例：

```bash
bash knowledge/pipielines_v3/run_all.sh --overwrite
```

单步 Python 的额外参数可放在 `run_config.sh` 中的 `STEP_0_ARGS`、`STEP_1_ARGS`、`STEP_2_ARGS`、`EMBEDDING_ARGS`、`RETRIEVAL_ARGS`、`STEP_4_ARGS` 数组里。任一步失败，当前入口立即停止；已经写入的 JSONL 行仍保留。总入口不会继续运行后续步骤。
