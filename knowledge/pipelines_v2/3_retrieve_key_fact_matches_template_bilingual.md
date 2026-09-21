# 领域知识检索模板 / Domain Knowledge Retrieval Template

用于 v2 第 3 步的 presentation。实现直接复用原版 `knowledge/pipelines/3_retrieve_knowledge.py`，本步骤没有 LLM 提示词。运行方式见 [步骤说明](3_retrieve_key_fact_matches.md)。

For presentation of v2 step 3. The implementation reuses the original `knowledge/pipelines/3_retrieve_knowledge.py`. This stage has no LLM prompt. See the linked stage guide for execution instructions.

# 中文模板

## 一、任务与输入

根据实现问题构造思路和四类答案构造思路所需的外部知识，从第 1 步所选领域中检索相关原子样本，为最终融合问题生成提供材料。

- 步骤 2 的输入记录包含源样本、key facts、`fusion_domains`、`domain_count`、`question_plan`、`answer_plans` 和 `required_key_facts`。领域由模型选出，逐条读取，不再手动指定。
- 向量库包含原始问答快照、对应语义向量、长文本分块映射和需求 query 向量。新需求先通过 `embed_required_key_facts.py --kind queries` 编码到同一个库中。
- 步骤 0 标注库为检索候选提供 key facts，通过领域和规范化原始问答关联，不能只按行号对应。

## 二、检索模板与规则

```text
目标领域 = 当前记录 fusion_domains 中的一个领域
queries = [entry.key_fact for entry in required_key_facts[目标领域]]
语料文本 = sample.prompt + "\n" + sample.completion
```

1. 每个目标领域有三个 query；每个 query 分别用 BM25 和预计算 embedding 余弦相似度检索，默认各 top 10。
2. 两路检索基于同一个库内问答快照；长文本语义分数取最高分块相似度。
3. 排除与源样本相同的问答，按 RRF 合并：`sum(1 / (60 + rank))`，排名从 1 开始，每领域默认最多 20 条。
4. 为候选匹配步骤 0 的 key facts，保留原始问答、候选标识、来源、分数和命中详情。

检索阶段只读已存向量，不加载模型、不调用 embedding API，也不自动回退到关键词模式。显式 `--method bm25` 可选择仅 BM25，读取原始 atomic 语料，默认 train。混合模式未设置 `--splits` 时使用库内划分，设置时要求与库内一致。

## 三、新增输出模板

下例仅展示一个所选领域的一个候选；实际按每条记录的全部 `fusion_domains` 展开。

```json
{
  "retrieved_samples": {
    "medical": [
      {
        "candidate_id": "medical:<sample_hash>",
        "source_file": "原始语料文件路径",
        "source_line": 1,
        "source_domain": "medical",
        "model": "该样本的key facts标注模型",
        "sample": {"prompt": "候选原始问题", "completion": "候选原始答案"},
        "key_facts": ["候选关键词组1", "候选关键词组2"],
        "rrf_score": 0.01639344262295082,
        "hits": [{"query_index": 1, "method": "embedding", "rank": 1, "score": 0.82}],
        "matches": [{"query_index": 1, "method": "embedding", "rank": 1, "score": 0.82, "required_key_fact": "对应需求短语"}]
      }
    ]
  }
}
```

`method` 为 `bm25` 或 `embedding`；`query_index` 为三个需求中的序号，从 1 开始。分数仅用于排序，不表示候选知识充分或事实正确。
输出还保存步骤 2 的完整内容，以及原版 `retrieval` 字段：实际方法、划分、每路 top-k、候选上限、RRF 参数；混合模式另外记录 embedding 模型、revision、配置哈希、库路径、分块参数、query 指令和语料来源。

缺少已保存的需求向量或候选 key facts 时明确报错，不伪造标注、不隐式调用模型。重复问答的标注冲突也报错。完成的行即时写入并在错误后保留。最终阶段读取这些材料及其 key facts 来实现构造思路。

# English Template

## 1. Task and Input

Retrieve relevant atomic samples from the domains selected in step 1, using the external knowledge requirements needed to realize the question-construction idea and four answer-construction ideas. The retrieved material supports final fusion-question generation.

- Step-2 records contain the source sample, key facts, fusion_domains, domain_count, question_plan, answer_plans, and required_key_facts. Domains were selected by the model and are read per record rather than supplied manually.
- The vector store contains original question-answer snapshots, semantic vectors, long-document chunk mappings, and requirement query vectors. Encode new requirements into the same store with embed_required_key_facts.py --kind queries beforehand.
- Step-0 annotations supply key facts for retrieved candidates, joined by domain and normalized original question-answer content, not by line number alone.

## 2. Retrieval Template and Rules

```text
Target domain = one domain in the current record's fusion_domains
queries = [entry.key_fact for entry in required_key_facts[target_domain]]
Corpus text = sample.prompt + "\n" + sample.completion
```

1. Each target domain has three queries. Retrieve the top 10 per query using BM25 and precomputed embedding cosine similarity independently.
2. Both methods use the same saved question-answer snapshot. For long documents, the semantic score is the maximum chunk similarity.
3. Exclude question-answer duplicates of the source sample and fuse rankings using RRF: sum(1 / (60 + rank)), with ranks starting at 1. Retain at most 20 candidates per domain by default.
4. Join each candidate to its step-0 key facts and retain the original question-answer pair, ID, provenance, score, and hit details.

Retrieval only reads saved vectors. It does not load a model, call an embedding API, or silently fall back to lexical search. Explicit --method bm25 selects BM25 only over the original atomic corpus, defaulting to train. Hybrid mode uses saved splits unless --splits is supplied, in which case an exact match is required.

## 3. Added Output Template

This example shows one candidate from one selected domain. Expand it for all fusion_domains in each record.

```json
{
  "retrieved_samples": {
    "medical": [
      {
        "candidate_id": "medical:<sample_hash>",
        "source_file": "Original corpus file path",
        "source_line": 1,
        "source_domain": "medical",
        "model": "Key-fact annotation model",
        "sample": {"prompt": "Original candidate question", "completion": "Original candidate answer"},
        "key_facts": ["Candidate phrase 1", "Candidate phrase 2"],
        "rrf_score": 0.01639344262295082,
        "hits": [{"query_index": 1, "method": "embedding", "rank": 1, "score": 0.82}],
        "matches": [{"query_index": 1, "method": "embedding", "rank": 1, "score": 0.82, "required_key_fact": "Corresponding requirement phrase"}]
      }
    ]
  }
}
```

method is bm25 or embedding; query_index is the one-based index of the requirement. Scores indicate ranking, not knowledge sufficiency or factual correctness.
Saved rows also retain the complete step-2 content and the original retrieval settings: method, splits, top-k per method, candidate limit, and RRF constant. Hybrid mode additionally records embedding model, revision, configuration hash, store path, chunking parameters, query instruction, and corpus sources.

Missing query vectors or candidate key-fact annotations cause an explicit error, without fabricating annotations or silently invoking a model. Conflicting annotations for duplicate question-answer pairs are rejected. Completed rows are flushed immediately and retained on failure. The final stage uses these samples and their key facts to realize the construction ideas.
