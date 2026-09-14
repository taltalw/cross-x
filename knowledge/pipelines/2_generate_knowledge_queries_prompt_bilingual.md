# 领域知识需求生成 / Knowledge Query Generation

步骤 3 为步骤 1 的每条 `feasible` 融合思路生成检索短语。每个 `fusion_domains` 领域生成恰好 3 个 query，分别覆盖核心概念、机制或条件、以及支撑答案所需的具体事实/规则/方法。跳过 `not_feasible`；不生成 joint query。

输出示例：

```json
{
  "source_domain": "chemistry",
  "sample": {"prompt": "Original question", "completion": "Original answer"},
  "fusion_domains": ["medical"],
  "fusion_idea": "The planned fusion idea.",
  "queries": {"medical": ["phosphine inhalation acute toxicity", "phosphine exposure supportive oxygen therapy", "phosphine first aid evacuation guidance"]}
}
```

Query 应是可直接搜索的短语，通常 3–12 个内容词；避免完整问题、泛泛关键词、仅重复原问题、编造数字或未经支持的假设。

## 中文模板

你负责跨领域知识数据集构造的第③步：生成领域知识检索 query。

输入原始问题和一条涉及 `fusion_domains` 的可行融合思路。请针对每个 `fusion_domains` 领域，判断该领域需要什么知识才能解决计划中的跨领域问题，并生成恰好 3 个用于从该领域检索相关样本或知识条目的短语。不要为原始领域生成 query，不要生成联合 query。

原始问题：

```text
{original_question}
```

可行融合思路：

```text
{fusion_idea}
```

融合领域及介绍：

```text
{fusion_domains}
```

要求：

1. 这些 query 用于从对应融合领域的数据中检索能够支撑构题的样本或知识条目。要依据融合思路判断：为了构造并解决跨领域问题，该领域的样本需要具备哪方面的知识。
2. 每个融合领域恰好输出 3 个 query，不能多也不能少。
3. query 应为可直接用于搜索的简短名词短语或关键词串，而不是完整问题或完整句子。
4. 尽量分别覆盖：核心概念/实体；机制、关系或条件；支撑答案所需的具体事实、规则或方法。应根据当前融合思路调整分类。
5. 每个 query 必须围绕融合思路中的具体实体、过程、条件或答案需求，不能只重复原始问题。
6. 避免“medical knowledge”“important chemistry facts”等泛泛 query，也不要把整个跨领域问题写成一个 query。
7. 使用权威领域材料中可能出现的术语；每个 query 通常为 3–12 个实质词。一个领域内的 3 个 query 应有明显区别。
8. 不编造引用、数字或没有依据的假设。

只输出 JSON：

```json
{"queries": {"fusion_domain_1": ["query 1", "query 2", "query 3"]}}
```

## English Template

You generate retrieval queries for step 3 of a cross-domain knowledge dataset.

The input contains an original question and one feasible fusion idea involving `fusion_domains`. For each fusion domain, determine what knowledge that domain needs to contribute in order to solve the planned cross-domain question, then generate exactly three concise search phrases for retrieving suitable samples or knowledge entries from that domain. Do not generate queries for the source domain or a joint query.

Original question:

```text
{original_question}
```

Feasible fusion idea:

```text
{fusion_idea}
```

Fusion domains and descriptions:

```text
{fusion_domains}
```

Requirements:

1. The queries are used to retrieve samples or knowledge entries from each fusion domain that could support construction of the planned cross-domain question. Infer what type of knowledge each fusion domain must provide to solve the question, based on the fusion idea.
2. Generate exactly three queries for every fusion domain.
3. Queries must be directly usable search phrases, preferably short noun phrases or compact keyword strings rather than complete questions or sentences.
4. Cover different retrieval needs: core concept/entity, mechanism/relationship/condition, and a specific fact/rule/method needed to support the answer. Adapt these categories to the current idea.
5. Anchor every query in concrete entities, processes, conditions, or answer requirements from the fusion idea. Do not merely repeat the original question.
6. Avoid vague queries such as “medical knowledge” or “important chemistry facts”, and avoid turning the entire cross-domain question into one query.
7. Use terminology likely to occur in authoritative domain materials. Keep each query concise, normally 3–12 content words. Queries within one domain must be meaningfully different.
8. Do not invent citations, numbers, or unsupported assumptions.

Output only JSON:

```json
{"queries": {"fusion_domain_1": ["query 1", "query 2", "query 3"]}}
```
