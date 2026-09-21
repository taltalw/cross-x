# 融合问题生成提示词 / Fusion Question Generation Prompt

用于 `pipelines_v2` 第 4 步的 presentation 与模板对照。包含中文语义模板、脚本实际使用的完整英文系统模板，以及输入字段介绍。运行方法见 [步骤说明](4_generate_fusion_question.md)。

脚本：`4_generate_fusion_question.py`；系统提示词变量：`SYSTEM_PROMPT`。中文部分用于解释模板语义，实际请求使用英文模板，要求模型生成英文内容；JSON 字段名和枚举值在中英文中保持一致。

For presentation and comparison of step 4 in pipelines_v2. The Chinese section explains the template; the English system prompt is copied from the script. Runtime output is English, and JSON keys and enum values are unchanged between languages.

## 消息组织 / Message Structure

`system` 消息使用下方英文 `SYSTEM_PROMPT`。每条样本的数据单独组织为 JSON 对象，经 `json.dumps(..., ensure_ascii=False)` 序列化后写入 `user` 消息；数据没有直接插入 system 模板。

The system message contains the English SYSTEM_PROMPT below. Per-sample data is serialized as JSON in a separate user message; it is not interpolated into the system prompt.

| 用户消息字段 / User field | 中文说明 | English description |
| --- | --- | --- |
| `source_domain` | 源领域 | Source domain |
| `sample` | 原始问答 | Original question and answer |
| `key_facts` | 源样本关键词组 | Source key facts |
| `fusion_domains` | 新增领域列表 | Additional domains |
| `question_plan` | 完整问题构造思路 | Complete question-construction idea |
| `answer_plans` | 四类答案构造思路 | Four answer-construction ideas |
| `required_key_facts` | 每个新增领域恰好三个需求及用途 | Exactly three requirements and their uses per additional domain |
| `retrieved_samples` | 各领域完整候选问答、key facts 和匹配信息 | Full candidate question-answer samples, key facts, and match information per domain |
| `option_count` | 固定为 4 | Always 4 |

## 领域选择与数量 / Domain Selection and Count

第 1 步只指定 `--domain-count N`，由模型结合原子样本和 key facts，从其余六个候选领域中选择一个合适的组合。N 沿用原版定义，包含源领域：N=3 时选择两个新增领域，总共三个领域。不再使用 `--fusion-domains` 参数。

模型选择的领域保存为 `fusion_domains`，每条样本可以不同。第 2–4 步从记录读取它们；这些步骤的 `--domain-count` 是可选的一致性校验参数，不重新指定领域。领域数不改变四类答案的约定。

Step 1 takes only --domain-count N. Using the atomic sample and its key facts, the model selects one suitable combination from the other six candidate domains. N includes the source domain: N=3 means two additional domains and three total. There is no --fusion-domains option.

The selected domains are saved as fusion_domains and can differ between samples. Steps 2–4 read them from each record; their optional --domain-count argument checks consistency rather than selecting domains. Domain count does not change the four answer types.

# 中文模板

你负责利用各领域的样本和 key facts，结合问题构造思路和四类答案构造思路，构造一道完整的跨领域选择题。

源领域材料来自原始样本及其 key facts，其他领域材料来自检索样本及其 key facts。沿用第 1 步选出的 `fusion_domains`，不添加或替换领域。

输入包含原始原子样本及其 key facts、问题构造思路（`question_plan`）、四类答案构造思路（`answer_plans`）、每个融合领域恰好三个 required key facts，以及带有 key facts 的检索原子样本。使用提供的材料作为依据，不要通过编造领域事实填补缺口。按照构造思路设计融合多领域知识的联合任务，并保留原始样本的核心知识。跨领域问题需要每个参与领域的专业知识围绕同一个任务目标共同发挥作用。仅更换背景、添加术语或拼接无关问题，不构成有效融合。将简洁的思路展开为具备全部必要条件的完整问题和四个具体选项。

构造恰好四个不同且合理的选项：

- `correct`：正确整合所有必要领域事实及其关系。
- `missing_domain_knowledge`：遗漏一个参与领域中的某项必要知识。
- `parallel_knowledge`：分别使用各领域事实，但未考虑必要的相互作用。
- `incorrect_domain_relation`：错误连接相关领域事实。

正确选项可以是 A、B、C 或 D。解释正确推理，并为三种错误选项类型各提供一项分析。每个融合领域至少使用一条检索候选，并返回其准确的 `candidate_id`。如果需要对参考思路作实质调整，在 `plan_adjustment` 中说明；否则使用空字符串。实际输出使用英文，只返回以下 JSON 对象：

```json
{
  "question": "包含所有必要条件的完整问题。",
  "options": {"A": "选项A", "B": "选项B", "C": "选项C", "D": "选项D"},
  "answer": "B",
  "explanation": "如何根据各参与领域的知识得出正确选项。",
  "distractor_analysis": [
    {"option": "A", "type": "missing_domain_knowledge", "missing_domain": "实际参与领域", "reason": "遗漏了什么必要知识，以及如何导致错误答案。"},
    {"option": "C", "type": "parallel_knowledge", "missing_domain": null, "reason": "分别使用了哪些事实，以及忽略了什么必要联系。"},
    {"option": "D", "type": "incorrect_domain_relation", "missing_domain": null, "reason": "错误连接了什么领域关系，以及如何导致错误答案。"}
  ],
  "used_material_ids": ["提供的候选标识原文"],
  "plan_adjustment": ""
}
```

# English Template

You use samples and key facts from all participating domains, together with
the question-construction idea and four answer-construction ideas, to construct
one complete cross-domain multiple-choice question.

The source domain is represented by the original sample and its key facts;
the additional domains are represented by retrieved samples and their key facts.
Use the fusion_domains selected in step 1 without adding or replacing domains.
The input includes an original atomic sample and its key facts, a question
construction idea (question_plan), four answer-construction ideas (answer_plans),
exactly three required key
facts for each fusion domain, and retrieved atomic samples with their key facts.
Use the supplied material as evidence. Do not invent domain facts to fill a gap.
Follow the construction ideas to design one joint task integrating knowledge
from multiple domains, and retain the original sample's core knowledge.
A cross-domain question requires specialized knowledge from every participating
domain to work together toward the same task objective. Merely changing the
setting, adding terminology, or concatenating unrelated questions does not
constitute valid fusion. Develop the concise ideas into a complete question
with all necessary conditions and four concrete answer options.

Create exactly four distinct, plausible options:
- correct: correctly combine all required domain facts and their relationships;
- missing_domain_knowledge: omit one necessary fact from one participating domain;
- parallel_knowledge: use domain facts separately but fail to account for their
  necessary interaction;
- incorrect_domain_relation: connect relevant domain facts incorrectly.

The correct option may be A, B, C, or D. Explain the correct reasoning and give
one analysis for each of the three wrong-option types. Use at least one retrieved
candidate from every fusion domain and return its exact candidate_id. If the
construction ideas need a substantive adjustment, describe it in plan_adjustment;
otherwise use an empty string. Return English text and only this JSON object:

{
  "question": "Complete question with all necessary conditions.",
  "options": {"A": "...", "B": "...", "C": "...", "D": "..."},
  "answer": "B",
  "explanation": "Why the correct option follows from the participating domains.",
  "distractor_analysis": [
    {"option": "A", "type": "missing_domain_knowledge", "missing_domain": "domain", "reason": "..."},
    {"option": "C", "type": "parallel_knowledge", "missing_domain": null, "reason": "..."},
    {"option": "D", "type": "incorrect_domain_relation", "missing_domain": null, "reason": "..."}
  ],
  "used_material_ids": ["exact supplied candidate_id"],
  "plan_adjustment": ""
}

## 输出与保存 / Response and Saved Record

模型只生成题目、选项、答案、解释、干扰项分析、材料引用和思路调整。程序另行保留 plans、required key facts、全部 retrieved samples 和来源信息。示例中的 B 不是固定正确位置；当前程序不另行随机打乱选项。

The model generates the question, options, answer, explanation, distractor analyses, material references, and plan adjustment. The program retains the plans, required key facts, all retrieved samples, and source metadata. B is illustrative; the current program does not separately shuffle options.
