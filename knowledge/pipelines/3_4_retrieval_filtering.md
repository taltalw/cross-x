# 需求驱动的检索与过滤

这两个脚本分别实现构造流程第④步的检索和过滤，可独立运行。

## 检索：直接读取完成的 embedding

流程：步骤 2 的 query JSONL → 本地向量检索与 BM25 → 步骤 3 的候选 JSONL → 独立的步骤 4 LLM 过滤。

默认向量目录为 `knowledge/embeddings/Qwen3-Embedding-8B/`，读取其中的 `vectors.sqlite3`。该数据库保存了七个领域的原始问答、来源、文档块向量和两组 query 的向量。模型信息直接从库内配置读取，**不需要传模型名、API 地址或 Key，不重新生成 embedding**。

```bash
cd /mnt/data1/wangyatong/cross-x
nohup bash knowledge/pipelines/run_3_retrieve_knowledge.sh \
  > knowledge/pipelines/run_3_retrieve_knowledge.log 2>&1 &
```

两组输入分别为 `results_5.5/2_generate_knowledge_queries/` 和 `results_6/2_generate_knowledge_queries/`，结果保存到各自的 `3_retrieve_knowledge/`。

需要改变向量位置时，只修改 Shell 的 `EMBEDDING_ROOT` 或向 Python 传入 `--embedding-root /path/to/vector-directory`。索引准备方式见 [EMBEDDING.md](EMBEDDING.md)。

每个融合领域独立检索：3 个 query 分别进行 BM25 和向量余弦检索，各取前 10 条；长样本按向量库已有的 token 分块计算，取最高块相似度作为样本分数。采用 RRF 合并六份排名，贡献为 `1 / (60 + rank)`，去重后最多保留 20 条候选。

BM25 使用向量库中的完整 `prompt + completion`，与向量索引保持同一语料快照。排除与原始 A 样本相同的问答。默认使用库中已有划分；显式 `--splits train` 时检查是否与库内划分一致。缺少语料或 query 向量时明确报错，不自动重编码。

检索环境只需要 Python 标准库和 NumPy，无需 GPU、模型权重或 Transformers。显式 `--method bm25`（Shell 用 `METHOD=bm25`）可仅从 `atomic/<domain>/train.jsonl` 进行关键词检索。

输出保留原始问答、融合领域、融合思路、queries，新增 `candidates` 和 `retrieval`：候选包含完整问答、`candidate_id`、来源文件与行号、RRF 分数及命中的 query/方法/排名。`retrieval` 记录向量库内的模型配置和检索参数；这些是自动记录的信息，不是运行所需的模型参数。

## LLM 过滤

过滤只读取保存的检索结果，不访问原子语料、不重新检索、不调用 embedding 服务。

1. 默认每批最多 5 条候选，读取完整问题与答案。判断实际提供的知识及适用条件，保留部分有用的材料。
2. 对保留候选进行整体覆盖检查，最多选 3 条互补材料，返回 `sufficient`、`partial` 或 `none`。判断针对最终选中的材料，而非所有候选。

保留决定必须给出原文证据；程序校验引用确实出现在对应问答字段中。选择题错误选项不能直接当作正确知识。此校验只能保证引用存在，不能替代知识正确性与适用性的最终验收。

没有召回候选时直接标记 `none`，不调用 LLM。所有候选被拒绝时仍询问覆盖模型，得到具体缺失知识。过滤不自动改写 query 或重新检索；`missing_knowledge` 用于后续回退，两步保持独立。

在 `run_4_filter_knowledge.sh` 中分别配置：

```bash
# results_5.5
export API_BASE_URL_5_5="https://your-provider/v1"
export API_KEY_5_5="your-key"
export MODEL_5_5="your-filter-model"
# results_6
export API_BASE_URL_6="https://your-provider/v1"
export API_KEY_6="your-key"
export MODEL_6="your-filter-model"

bash /mnt/data1/wangyatong/cross-x/knowledge/pipelines/run_4_filter_knowledge.sh
```

各组 `3_retrieve_knowledge/` → 各组 `4_filter_knowledge/`，API、Key、模型分别对应。

单文件沿用 `API_BASE_URL`、`API_KEY`、`MODEL`：

```bash
python3 /mnt/data1/wangyatong/cross-x/knowledge/pipelines/4_filter_knowledge.py \
  --input /path/to/candidates.jsonl --output /path/to/filtered.jsonl
```

最终输出保留基本信息并增加 `knowledge`，不再重复全部检索候选：

```json
{
  "medical": {
    "status": "partial",
    "materials": [
      {
        "candidate_id": "medical:<content-hash>",
        "source_file": "/path/to/train.jsonl",
        "source_line": 123,
        "sample": {"prompt": "完整问题", "completion": "完整答案"},
        "supported_knowledge": "该样本实际支持的知识及其在融合任务中的用途。",
        "evidence": [{"field": "completion", "quote": "完整答案"}]
      }
    ],
    "missing_knowledge": "仍缺少的关键知识。"
  }
}
```

`sufficient` 必须有材料且缺口为空；`partial` 必须有材料且说明缺口；`none` 材料为空且说明缺口。三个 query 不要求一一匹配三条材料。

## 运行与复用

- 两个 Python 入口均支持 `--input file1.jsonl file2.jsonl`，多文件搭配 `--output-root`；`--output` 仅用于单文件。
- 输出分别加 `3_`、`4_` 前缀，保留输入文件名中的领域数量标识。
- 已有结果默认禁止覆盖；`--overwrite` 从头写入输出。过滤判断按完整输入、提示词、API 地址和模型缓存到 `cache/filter/judgments.sqlite3`，已完成的相同调用可复用。缓存不保存 Key。
- HTTP 临时错误或结构错误默认重试 2 次；鉴权等配置错误立即停止。失败时保留已完成的输出行及已提交缓存。
- `--max-input-chars` 默认 120,000，控制过滤请求的字符预算。批次会按预算缩小，仍过长的单条候选或整体覆盖请求会明确报错，不静默截断。应根据模型上下文设置预算，或减少检索候选数量。
- 常用参数：检索 `--top-k 10 --candidate-limit 20`；过滤 `--batch-size 5 --max-materials 3`。

完整中英文过滤模板见 `4_filter_knowledge_prompt_bilingual.md`。
