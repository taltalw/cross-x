# 第 4 步：根据各领域样本和构造思路生成问题

你负责利用各领域的样本和 key facts，结合问题构造思路和四类答案构造思路，构造一道完整的跨领域选择题。

完整中英文提示词和模型响应 JSON 见 [双语模板](4_generate_fusion_question_prompt_bilingual.md)。

## 输入模板

输入为步骤 3 输出。源领域使用 `sample` 和 `key_facts`；第 1 步所选新增领域使用 `retrieved_samples[domain]` 内的原始问答和 key facts。沿用 `fusion_domains`，每条记录可以不同。

发送给模型的用户对象包含：`source_domain`、`sample`、`key_facts`、`fusion_domains`、`question_plan`、`answer_plans`、`required_key_facts`、`retrieved_samples`、`option_count: 4`。

## 输出模板与字段

| 字段 | 含义 |
| --- | --- |
| `question` | 完整融合问题，所有领域共同服务于同一个目标 |
| `options` | A–D 四个不同的选项 |
| `answer` | 正确标签，由模型决定位置 |
| `explanation` | 正确的跨领域推理 |
| `distractor_analysis` | 缺失领域知识、简单并列、错误领域关系三类分析 |
| `used_material_ids` | 实际候选 ID，每个新增领域至少使用一条 |
| `plan_adjustment` | 构造思路的实质调整，无调整时为空字符串 |

完整保存源样本字段、`fusion_domains`、`domain_count`、`question_plan`、`answer_plans`、`required_key_facts`、`retrieved_samples`、`retrieval` 和生成字段；`model` 更新为本步骤模型。全部候选会保存，不只保存实际使用的候选。

## 运行

```bash
SOURCE_DOMAIN=geography DOMAIN_COUNT=3 NUM=10 \
bash knowledge/pipelines_v2/run_4_generate_fusion_question.sh
```

Python 的 `--domain-count` 仅校验输入，不选择领域。任一领域无候选时停止报错；超出 `--max-input-chars` 也报错，不截断原文。结构校验不代表已完成事实正确性、唯一可解性和跨领域必要性的人工验收。

已有输出需要 `--overwrite` 才能覆盖；逐行写入并保留失败前已完成的结果。
