# 三段串行入口：012 → embedding/retrieve → 4

统一配置文件是 [run_config.sh](run_config.sh)。可直接在其中填写 API 地址、Key、模型、Python 环境和数据目录，也可使用同名环境变量。三个入口都从这份配置读取参数，不需要逐个修改单步脚本。

```bash
cd /mnt/data1/wangyatong/cross-x

# 按顺序运行；每段也可以单独启动。
bash knowledge/pipelines_v2/run_012.sh && \
bash knowledge/pipelines_v2/run_embedding_retrieve.sh && \
bash knowledge/pipelines_v2/run_4.sh
```

## 第一段：0 → 1 → 2

入口：[run_012.sh](run_012.sh)。

1. 对七个领域的完整 `atomic/<domain>/test.jsonl` 提取 key facts，不传 `--num`。
2. 遍历七个源领域 × 总领域数 2、3、4，共 21 组。每个源样本由 LLM 选择其他领域并生成一套构题思路和四类答案思路。
3. 对步骤 1 的全部输出逐条提取 required key facts，每个已选新增领域恰好 3 个。

`DOMAIN_COUNT` 的语义仍为总参与领域数：2=A+B，3=A+B+C，4=A+B+C+D。这是三种领域数量设置，不是每条样本输出 2、3、4 个备选组合。

`NUM` 只控制第 1 步每组读取的源样本数，默认 10。每组输入够用时产生 10 条，共 210 条；输入少于 NUM 时处理到文件结束。步骤 0 始终标注全部 test 样本；步骤 2 处理步骤 1 的全部结果，不另行限量。

```bash
# 第 1 步每组也处理全部源样本；第 0 步本来就是全量。
NUM=all bash knowledge/pipelines_v2/run_012.sh
```

## 第二段：embedding → retrieve

入口：[run_embedding_retrieve.sh](run_embedding_retrieve.sh)。不需要 LLM API 凭据。

1. 调用原版 `embed_knowledge.py`，对七领域完整原始 test 问答生成语料向量。
2. 调用 v2 `embed_required_key_facts.py`，对第一段产生的 21 个需求文件生成 query 向量。
3. 对这 21 组结果依次混合检索：BM25 + embedding cosine + RRF，默认每个需求、每种方法 top 10，每个融合领域最多 20 条候选。

语料和需求向量使用同一个库，默认 `knowledge/embeddings/v2-test-Qwen3-Embedding-8B`。默认新建独立 test 库；已有兼容库会复用缓存。不会覆盖原版 train 库，也不会因为传入 `--overwrite` 就重建向量库。语料或模型配置变化时，由原版向量存储层提示冲突，应指定新库或按原版方式显式处理。

检索对候选关联步骤 0 的 key facts，且显式指定 test 划分。不要将 test 标注与 train 向量混用。

`EMBEDDING_PYTHON_BIN` 可单独指向安装了 PyTorch、transformers 等依赖的 Python；`PYTHON_BIN` 用于其余步骤，检索还需要 NumPy。模型默认 `Qwen/Qwen3-Embedding-8B`，可在统一配置中设置 `EMBEDDING_MODEL`、`EMBEDDING_DEVICE`、`EMBEDDING_DTYPE` 和 `EMBEDDING_BATCH_SIZE`。模型首次运行可能需要下载。

## 第三段：4

入口：[run_4.sh](run_4.sh)。读取第二段的全部 21 组结果，生成四选项融合问题。保存各领域样本、key facts、构造思路、检索结果和生成内容，不再单独限制处理条数。

## 输出与运行行为

全部结果位于 `V2_ROOT`，默认 `knowledge/pipelines_v2/outputs`：

```text
0_extract_key_facts/<source>/test.jsonl
1_generate_fusion_plans/<source>/test_domain_count_2.jsonl
2_extract_required_key_facts/<source>/test_domain_count_2.jsonl
3_retrieve_key_fact_matches/<source>/test_domain_count_2.jsonl
4_generate_fusion_question/<source>/test_domain_count_2.jsonl
```

1–4 步另外各有 `_domain_count_3.jsonl`、`_domain_count_4.jsonl`。三个入口必须使用同一份 `V2_ROOT`、`ATOMIC_ROOT` 和 `EMBEDDING_ROOT` 配置。旧的 `INPUT_ROOT`、`OUTPUT_ROOT`、`SOURCE_DOMAIN` 单步变量不控制这三个入口。

每段在启动前检查所需输入和已有输出；默认保护已有文件。传 `--overwrite` 会从头重跑该段并替换该段的 JSONL 输出，属于重跑而非断点续跑：

```bash
bash knowledge/pipelines_v2/run_012.sh --overwrite
bash knowledge/pipelines_v2/run_embedding_retrieve.sh --overwrite
bash knowledge/pipelines_v2/run_4.sh --overwrite
```

任一步失败立即停止该入口，已写完的记录保留；用 `&&` 连接三个入口时也不会继续到下一段。统一入口只接受 `--overwrite`；`--max-tokens`、`--timeout` 等分别填入配置中的 `STEP_0_ARGS`、`STEP_1_ARGS`、`STEP_2_ARGS`、`STEP_4_ARGS`。embedding 和检索分别使用 `EMBEDDING_ARGS`、`RETRIEVAL_ARGS`。这些数组不应用来覆盖输入输出、领域数量或数据划分。

入口只产生任务 JSONL 与必要的向量库，运行进度打印到终端，不自动创建审计文件或运行报告。
