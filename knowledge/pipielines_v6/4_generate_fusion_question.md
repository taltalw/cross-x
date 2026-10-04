# 第 4 步：简洁跨领域题生成（v6）

本版本保持原筛选流程不变：直接读取第 3 步记录，由筛选模型从现有检索证据中选择能支持所有参与领域的自然融合任务；`feasible=false` 仍按原逻辑跳过。修改只发生在筛选通过之后，所有新增运行逻辑集中在 `4_generate_fusion_question.py`。

## 通过筛选后的流程

```text
原筛选通过
  -> 派生只读 compact_blueprint 和长度预算
  -> easy / medium / hard 各生成一个候选
  -> 原结构/引用校验 + 局部硬长度检查
  -> 程序确定性打乱 A-D，同步 answer 和 distractor_analysis.option
  -> 独立答案标签盲审
  -> 通过：写正式题；失败：最多定向重写一次
  -> 重写仍失败：只写审计，保留 feasible=true，继续其他难度
```

筛选失败、空检索、输入错误、API/JSON 重试耗尽和生成质量拒绝分开记录。生成失败不会回写筛选结果，不重新筛选、不重新检索、不替换领域。一个筛选通过计划可以接受 0–3 道题；不强制凑齐三个难度。

## 题面与后台

可见题面只包含 `question` 和 `options`，另附统一答题指令。题干写必要情境、实例数据、假设、单位、边界和一个最终问题；选项用同一种语义形式给出最终结果。公共条件/公共代码只写一次。题面不放完整推理、检索文本、计划、错误标签或审查结果。

完整解法写入 `explanation`。三类干扰项仍各一次：

- `missing_domain_knowledge`：缺少或误用必要领域知识，产生具体错误结果。
- `parallel_knowledge`：局部知识或结果存在，但没有传入最终判断。
- `incorrect_domain_relation`：使用错误的映射、方向、对象或组合关系。

`distractor_analysis.reason` 必须说明“错误步骤 → 错误结果 → 对应选项”。短数字/短决策选项不需要自证错误类型；`error_label_status=construction_intent` 表示构造意图，不表示已证明模型认知机制。

## 生成输入与保存字段

生成调用沿用原筛选后的 `question_plan`、`answer_plans`、`required_key_facts` 和 selected_samples，额外加入派生的 `compact_blueprint`、`length_budget`、difficulty 和 option_count。派生 blueprint 是后台构造记录，不改变筛选响应：它记录一个最终 target、共同依赖摘要和各参与领域的作用；不会增加筛选准入字段。

顶层旧字段继续保存：`source_file`、`source_domain`、`model`、`sample`、`key_facts`、`fusion_domains`、`domain_count`、`question_plan`、`answer_plans`、`required_key_facts`、`retrieved_samples`、`retrieval`、`question`、`options`、`answer`、`explanation`、`distractor_analysis`、`used_samples`、`plan_adjustment`、`difficulty`。

新增 `item_id` 和 `construction`，其中包含：`version=v6-concise-1`、稳定 `plan_key`、`compact_blueprint`、原筛选前计划、selected_samples、完整 `retrieved_candidates`、`visible_fields=[question, options]`、预算与长度统计、排列映射、`semantic_audit`、`repair_count`、`difficulty_status=uncalibrated` 和 `error_label_status=construction_intent`。完整候选保留 `candidate_id`、`hits`、`matches`、评分及来源等旧检索元数据；旧输入行不会被改写。

代码/表达式选项由第 4 步局部保留合法换行、缩进和字符大小写，共享校验器的空白规范化不会落盘覆盖这些字段。超限只返回字段级问题并进入重写，绝不截断代码或删除必要条件。

## 长度预算

单位是英文 `len(text.split())`，只统计 question/options；字符保护默认是相应词数硬限的 12 倍。默认配置：

| 总领域数 | 题干软目标 | 题干硬上限 | 每选项硬上限 | 题干+四选项硬上限 |
|---:|---:|---:|---:|---:|
| 2 | 30–55 | 75 | 18 | 130 |
| 3 | 40–70 | 95 | 20 | 160 |
| 4 | 50–85 | 115 | 22 | 190 |

5–7 个领域按线性外推并标记 `uncalibrated_extension`。可用 `--length-budget-file` 覆盖完整预算；入口不传该参数时使用默认值。预算只进入生成/重写调用，不进入筛选 payload。

## CLI 与运行

保留原参数，并新增：

- `--max-repairs`：0 或 1，默认 1。
- `--seed`：默认 42，用于稳定选项排列。
- `--judge-model`：可选；默认复用生成模型配置。
- `--skip-semantic-audit`：仅格式调试，输出标 `not_run`，不能视为质量通过。
- `--length-budget-file`：完整预算 JSON，生成前验证。
- `--audit-output`：审计 JSONL 路径；未指定时为 output 同目录 `.audit.jsonl`。

直接运行第 4 步（不覆盖已有结果时不要加 `--overwrite`）：

```bash
cd /mnt/data1/wangyatong/cross-x
API_BASE_URL="https://your-provider/v1" \
API_KEY="your-key" \
MODEL="your-model" \
PYTHONDONTWRITEBYTECODE=1 python knowledge/pipielines_v6/4_generate_fusion_question.py \
  --input knowledge/pipielines_v6/outputs/3_retrieve_key_fact_matches/mathematics/test_domain_count_2.jsonl \
  --output knowledge/pipielines_v6/outputs_concise/mathematics_domain2.jsonl \
  --audit-output knowledge/pipielines_v6/outputs_concise_audit/mathematics_domain2.audit.jsonl \
  --domain-count 2 --num 3 --max-repairs 1 --seed 42
```

该命令只处理 3 个输入计划，最多尝试 9 个初稿，不重跑第 0–3 步，不覆盖旧结果。

## 验证与边界

允许的离线验证包括现有 v6 测试、仓库外临时 FakeAPI 和临时目录。应至少检查：筛选 prompt/payload/feasible 控制流未变、短选项不含错误解释、字段/字符/总长度超限进入重写、答案及干扰项映射同步、代码换行保留、审查输入不泄漏后台字段、API 失败保留已完成输出。

未进行真实模型生成时，不得声称生成质量、语义接受率、答案唯一性、跨领域依赖或长度改善已经验证。一次语义盲审也不是独立专家证明。
