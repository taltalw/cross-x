# 第 4 步：根据各领域样本和构造思路生成问题

先检查检索样本是否足以支持每项知识需求和联合构题思路；证据不足的方案直接跳过。通过筛选后，分别生成简单、中等、困难三道跨领域选择题。

完整中英文提示词和模型响应 JSON 见 [双语模板](4_generate_fusion_question_prompt_bilingual.md)。

## 输入模板

输入为步骤 3 输出。源领域使用 `sample` 和 `key_facts`；新增领域从 `retrieved_samples[domain]` 读取候选的原始问答。步骤 4 给模型传入按领域排列的 `sample`（`prompt`、`completion`），不传候选 ID。

筛选调用包含 `source_domain`、`sample`、`key_facts`、`fusion_domains`、`question_plan`、`answer_plans`、`required_key_facts` 和 `retrieved_samples`。模型判断检索材料是否充分，并直接列出支持方案的样本；程序检查这些样本是否来自对应领域。某领域没有候选时，直接跳过。

生成调用只传入筛选引用的候选，另加入 `option_count: 4` 和 `difficulty`（`easy`、`medium`、`hard`）。三种难度只通过提示词约束，不做程序化难度评估。

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

每个通过筛选的方案写入三条 JSONL；跳过的方案不写入题目文件。输出保留源样本、方案、需求、全部检索到的问答样本及生成字段，`model` 更新为本步骤模型。运行报告包含已处理方案数、跳过数和生成题数，跳过原因写到标准错误输出。

## 运行

```bash
bash knowledge/pipielines_v3/run_4.sh
```

入口处理全部七个源领域和三种领域数量。单步 Python 的 `--domain-count` 仅校验输入，不选择领域；`--num` 限制读取的方案数。任一领域无候选时跳过该方案；超出 `--max-input-chars` 仍报错，不截断原文。证据充分性由模型判断，结构校验不等于事实正确性、唯一可解性和跨领域必要性的人工验收。

已有输出需要 `--overwrite` 才能覆盖；逐行写入并保留失败前已完成的结果。
