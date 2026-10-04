# 第 4 步：根据各领域样本和构造思路生成问题

先从检索结果中选择能自然构造跨领域题的样本，按所选样本调整问题、答案思路和知识需求；没有合适组合时跳过。通过筛选后，分别生成简单、中等、困难三道跨领域选择题。

完整中英文提示词和模型响应 JSON 见 [双语模板](4_generate_fusion_question_prompt_bilingual.md)。

## 输入模板

输入为步骤 3 输出。源领域使用 `sample` 和 `key_facts`；新增领域从 `retrieved_samples[domain]` 读取候选的原始问答。步骤 4 给模型传入按领域排列的 `sample`（`prompt`、`completion`），不传候选 ID。

筛选调用包含 `source_domain`、`sample`、`key_facts`、`fusion_domains`、原 `question_plan`、原 `answer_plans` 和 `retrieved_samples`。原 plan 仅作参考，模型可以根据检索材料调整。可行时返回 `selected_samples`、更新后的 `question_plan`、`answer_plans` 和 `required_key_facts`；程序检查样本属于对应领域且四类答案及三个需求的结构有效。某领域没有候选时，直接跳过。

生成调用只传入所选样本和调整后的 plan、知识需求，另加入 `option_count: 4` 和 `difficulty`（`easy`、`medium`、`hard`）。生成阶段的 `SYSTEM_PROMPT` 未改动；三种难度只通过提示词约束，不做程序化难度评估。

## 输出模板与字段

| 字段 | 含义 |
| --- | --- |
| `question` | 简洁的融合问题，保留解题必要条件，不写额外推理步骤 |
| `options` | A–D 四个简洁且不同的选项，不写额外推理步骤 |
| `answer` | 正确标签，由模型决定位置 |
| `explanation` | 正确的跨领域推理 |
| `distractor_analysis` | 缺失领域知识、简单并列、错误领域关系三类分析 |
| `used_samples` | 按领域排列的实际使用样本，每个新增领域至少一条 |
| `plan_adjustment` | 构造思路的实质调整，无调整时为空字符串 |
| `difficulty` | 程序追加的难度标签：`easy`、`medium` 或 `hard` |

每个通过筛选的方案写入三条 JSONL；跳过的方案不写入题目文件。输出保存调整后的 plan 和需求，并保留源样本、全部检索到的问答样本及生成字段；原 plan 仍在步骤 3 的文件中。运行报告包含已处理方案数、跳过数和生成题数，跳过原因写到标准错误输出。

## 运行

```bash
bash knowledge/pipielines_v4/run_4.sh
```

入口处理全部七个源领域和三种领域数量。单步 Python 的 `--domain-count` 仅校验输入，不选择领域；`--num` 限制读取的方案数。任一领域无候选时跳过该方案；超出 `--max-input-chars` 仍报错，不截断原文。样本组合是否自然由模型判断，结构校验不等于事实正确性、唯一可解性和跨领域必要性的人工验收。

已有输出需要 `--overwrite` 才能覆盖；逐行写入并保留失败前已完成的结果。
