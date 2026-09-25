# 七领域 test 语料向量

在 `cross-x` 目录执行：

```bash
bash knowledge/pipelines_v2/run_embed_test_corpus.sh
```

脚本读取 `knowledge/atomic/<domain>/test.jsonl` 的全部问答，涵盖 medical、legal、financial、mathematics、computer_science、geography、chemistry 七个领域。先检查七个文件存在，再一次加载模型，依次生成各领域语料向量。

默认配置：

| 配置 | 默认值 |
| --- | --- |
| Python | `/mnt/data1/wangyatong/anaconda3/envs/crossx/bin/python` |
| 物理显卡 | GPU 1，仅此卡可见，进程内部为 `cuda:0` |
| 向量库 | `knowledge/embeddings/v2-test-Qwen3-Embedding-8B` |
| batch size | 8 |

复用原版 `embed_knowledge.py --kind corpus`：编码文本为 `prompt + 换行 + completion`；长文本按 token 分块，保存样本与分块映射，相同问答按领域去重。模型名、revision、dtype 和分块等设置从已有库中读取，与已生成的 query 向量保持一致；已有 query 向量会保留。若库不存在，原版默认使用 Qwen/Qwen3-Embedding-8B。

支持环境变量 `ATOMIC_ROOT`、`EMBEDDING_ROOT`、`PYTHON_BIN`、`GPU_ID`、`BATCH_SIZE`。例如减少批大小：

```bash
BATCH_SIZE=4 bash knowledge/pipelines_v2/run_embed_test_corpus.sh
```

可追加 `--local-files-only` 等原版参数。已存在且相同的语料快照复用缓存；语料内容变化时原版会报错，只有显式传 `--replace-corpus` 才替换快照。模型配置冲突不会被静默覆盖。

本脚本只生成语料向量，不调用 LLM、不重新生成 query 向量，也不运行检索。它读取原始 test 全集；此前缺少 key facts 的一条 legal 样本仍会参与编码，检索前需要另行处理该标注缺口。
