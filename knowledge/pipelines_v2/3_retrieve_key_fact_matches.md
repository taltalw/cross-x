# 第 3 步：检索领域知识样本

参考并直接复用原版 `knowledge/pipelines/3_retrieve_knowledge.py` 的 `Retriever`、BM25、embedding cosine 和 RRF。没有 LLM 提示词，检索阶段不加载模型、不调用 embedding API。

完整中英文输入/输出模板见 [双语检索模板](3_retrieve_key_fact_matches_template_bilingual.md)。

## 输入与检索方式

- `--input`：步骤 2 JSONL，读取每条记录的 `fusion_domains`。
- `--embedding-root`：原版 Qwen 向量库，包含语料问答、分块映射和 `(domain, query)` 向量。
- `--corpus`：步骤 0 的 key facts 标注文件或目录，用于给召回样本关联 key facts。
- `--atomic-root`：仅 `--method bm25` 时读取的原始语料，默认 `knowledge/atomic`。

把每个领域的 3 个 `required_key_facts[].key_fact` 作为 3 个 query。对库内相同的原始问答快照分别做 BM25 和语义向量检索，各 query、各方法默认 top 10。长样本的语义得分取最高分块余弦相似度。排除与源样本相同的问答后，按 `sum(1/(60+rank))` 合并去重，每领域默认最多 20 条。

本版不再使用 TF-IDF 作为向量检索。query 和语料必须处于同一个模型配置的向量库；新生成的 required key facts 必须预先生成向量。

## 关联 key facts

使用领域和规范化后的原始问答匹配步骤 0 标注，而不是按路径或行号对齐。缺少召回样本的 key facts 时明确报错，请先对检索语料运行步骤 0。仅标注了 test 前 10 条不能覆盖完整 train 检索库。
目录输入读取领域目录下的 JSONL，不读根目录的审计文件。重复问答的 key facts 冲突时拒绝处理。检索分数不等于知识覆盖程度或事实正确概率。

## 向量准备与运行

已有语料向量时直接复用；若没有，使用原版入口生成：

```bash
python knowledge/pipelines/embed_knowledge.py --kind corpus \
  --input knowledge/atomic --splits train \
  --embedding-root knowledge/embeddings/Qwen3-Embedding-8B

bash knowledge/pipelines_v2/run_embed_required_key_facts.sh

SOURCE_DOMAIN=geography DOMAIN_COUNT=3 \
bash knowledge/pipelines_v2/run_3_retrieve_key_fact_matches.sh
```

详情见 [向量准备说明](embed_required_key_facts.md)。`EMBEDDING_ROOT` 选择库，`CORPUS_ROOT` 选择标注库，`TOP_K`、`CANDIDATE_LIMIT` 控制召回数；`--rrf-k` 默认 60。`--splits` 在混合模式下要求与库中划分一致；不填则使用库内划分。仅关键词模式必须显式 `METHOD=bm25`，默认不会因向量缺失自动降级。

## 输出

保留源样本、源 key facts、所选领域、完整构造思路及 required key facts，增加 `retrieved_samples` 和 `retrieval`。候选含 `candidate_id`、`source_file`、`source_line`、`sample`、`source_domain`、`model`、`key_facts`、`rrf_score`、`hits`、`matches`；`matches` 在原版命中信息上增加对应需求短语。
`retrieval` 保存实际方法、库与模型配置、语料来源、分块和召回参数；候选的 `model` 是标注模型，顶层 `model` 继承步骤 2。

输出已有时需 `--overwrite`。向量缺失、标注缺失、输入不合法时停止并保留已完成行。空召回列表会传给步骤 4，由其拒绝缺少某领域材料的输入。
