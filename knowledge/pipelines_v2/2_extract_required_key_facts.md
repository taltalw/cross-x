# 第 2 步：提取构造任务所需的外部知识

输入包含原始原子样本、其 key facts、问题构造思路（`question_plan`）和四类答案构造思路（`answer_plans`）。为了按这些思路构造问题和四类答案，每个领域需要用到哪些知识？请为每个领域列出三个简短的英文知识点短语，用来检索包含这些知识的原子样本。

完整中英文提示词见 [双语模板](2_extract_required_key_facts_prompt_bilingual.md)。

## 输入与输出模板

输入为步骤 1 输出。模型收到 `source_domain`、`sample`、`key_facts`、`fusion_domains`、`question_plan`、`answer_plans` 和 `answer_plan_types`。领域在每条记录中独立读取，不再手工指定。`--domain-count` 可选，只校验与输入一致。

模型只返回 `required_key_facts`，每个新增领域恰好三项；以下只展示一个领域，实际键集合必须覆盖全部 `fusion_domains`。

```json
{
  "required_key_facts": {
    "medical": [
      {"key_fact": "具体知识需求短语1", "used_by": ["question", "correct"], "necessity": "实现构题思路为何需要此知识"},
      {"key_fact": "具体知识需求短语2", "used_by": ["missing_domain_knowledge"], "necessity": "构造该错误答案为何需要此知识"},
      {"key_fact": "具体知识需求短语3", "used_by": ["parallel_knowledge", "incorrect_domain_relation"], "necessity": "实现跨领域推理为何需要此知识"}
    ]
  }
}
```

`key_fact` 是简短英文知识需求；每领域三项不得重复。`used_by` 表示服务于问题或哪类答案，问题标识为 `question`。`necessity` 用一句话说明用途。知识需求不是已经证实的事实。
保存原始样本、源 key facts、领域配置及完整思路，增加 `required_key_facts`，更新 `model` 为本步骤模型。

## 运行

```bash
SOURCE_DOMAIN=geography DOMAIN_COUNT=3 NUM=10 \
bash knowledge/pipelines_v2/run_2_extract_required_key_facts.sh
```

输入/输出均采用 `<source>/<split>_domain_count_<N>.jsonl`。步骤 2 后，混合检索前需要为这些新需求预计算 query 向量，见 [向量准备](embed_required_key_facts.md)。

已有输出需要 `--overwrite` 才能覆盖；逐行写入并保留失败前已完成的结果。
