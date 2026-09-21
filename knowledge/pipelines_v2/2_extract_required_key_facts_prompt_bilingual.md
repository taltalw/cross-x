# 融合领域知识需求提示词 / Required Key Facts Prompt

用于 `pipelines_v2` 第 2 步的 presentation 与模板对照。包含中文语义模板、脚本实际使用的完整英文系统模板，以及输入字段介绍。运行方法见 [步骤说明](2_extract_required_key_facts.md)。

脚本：`2_extract_required_key_facts.py`；系统提示词变量：`SYSTEM_PROMPT`。中文部分用于解释模板语义，实际请求使用英文模板，要求模型生成英文内容；JSON 字段名和枚举值在中英文中保持一致。

For presentation and comparison of step 2 in pipelines_v2. The Chinese section explains the template; the English system prompt is copied from the script. Runtime output is English, and JSON keys and enum values are unchanged between languages.

## 消息组织 / Message Structure

`system` 消息使用下方英文 `SYSTEM_PROMPT`。每条样本的数据单独组织为 JSON 对象，经 `json.dumps(..., ensure_ascii=False)` 序列化后写入 `user` 消息；数据没有直接插入 system 模板。

The system message contains the English SYSTEM_PROMPT below. Per-sample data is serialized as JSON in a separate user message; it is not interpolated into the system prompt.

下方中文模板的“每个领域”指用户消息中 `fusion_domains` 列出的各个领域。

In the Chinese template below, “each domain” refers to the domains listed in `fusion_domains` in the user message.

| 用户消息字段 / User field | 中文说明 | English description |
| --- | --- | --- |
| `source_domain` | 源领域 | Source domain |
| `sample` | 原始问答 | Original question and answer |
| `key_facts` | 源样本关键词组 | Source key facts |
| `fusion_domains` | 需要补充知识的新增领域 | Additional domains supplying knowledge |
| `question_plan` | 步骤 1 的完整问题构造思路 | Complete question-construction idea from step 1 |
| `answer_plans` | 步骤 1 的四类答案构造思路 | Four answer-construction ideas from step 1 |
| `answer_plan_types` | 四类答案的固定英文标识列表 | Fixed list of the four answer-type identifiers |

## 领域选择与数量 / Domain Selection and Count

第 1 步只指定 `--domain-count N`，由模型结合原子样本和 key facts，从其余六个候选领域中选择一个合适的组合。N 沿用原版定义，包含源领域：N=3 时选择两个新增领域，总共三个领域。不再使用 `--fusion-domains` 参数。

模型选择的领域保存为 `fusion_domains`，每条样本可以不同。第 2–4 步从记录读取它们；这些步骤的 `--domain-count` 是可选的一致性校验参数，不重新指定领域。领域数不改变四类答案的约定。

Step 1 takes only --domain-count N. Using the atomic sample and its key facts, the model selects one suitable combination from the other six candidate domains. N includes the source domain: N=3 means two additional domains and three total. There is no --fusion-domains option.

The selected domains are saved as fusion_domains and can differ between samples. Steps 2–4 read them from each record; their optional --domain-count argument checks consistency rather than selecting domains. Domain count does not change the four answer types.

# 中文模板

你负责提取完成一个跨领域问题构造任务所需的外部知识。

输入包含原始原子样本、其 key facts、问题构造思路（`question_plan`）和四类答案构造思路（`answer_plans`）。为了按这些思路构造问题和四类答案，每个领域需要用到哪些知识？请为每个领域列出三个简短的英文知识点短语，用来检索包含这些知识的原子样本。每项需求应是具体概念、机制、规则、条件或关系；不要输出完整问题、泛泛的领域名称或属于其他领域的事实。

覆盖问题构造思路和答案构造思路实际需要的知识，包括支撑跨领域推理联系的知识。每个领域的三项需求必须互不重复，并能共同发挥作用。用以下标识说明每项知识服务于哪些构造思路：`question`、`correct`、`missing_domain_knowledge`、`parallel_knowledge`、`incorrect_domain_relation`。用一句简短的话解释每项知识为什么必要。不要仅为凑足数量而编造知识。

只返回以下 JSON 对象。按实际 `fusion_domains` 为每个领域提供三项；`domain_a` 是领域标识占位符。

```json
{
  "required_key_facts": {
    "domain_a": [
      {"key_fact": "具体知识短语1", "used_by": ["question", "correct"], "necessity": "为什么需要这项知识。"},
      {"key_fact": "具体知识短语2", "used_by": ["correct", "missing_domain_knowledge"], "necessity": "为什么需要这项知识。"},
      {"key_fact": "具体知识短语3", "used_by": ["question", "parallel_knowledge"], "necessity": "为什么需要这项知识。"}
    ]
  }
}
```

# English Template

You extract the external knowledge needed to complete a cross-domain
question-construction task.

The input contains an original atomic sample, its key facts, a question-construction
idea (question_plan), and four answer-construction ideas (answer_plans).
What knowledge does each domain in fusion_domains need to provide to construct
the question and four types of answers following these ideas? For each domain,
list exactly three short English key-fact phrases to retrieve atomic samples
that contain this knowledge. A required key fact must be a concrete concept,
mechanism, rule, condition, or relationship; do not output a complete question,
generic domain labels, or facts belonging to another domain.

Cover what the question-construction idea and answer-construction ideas actually
need, including the knowledge needed for their cross-domain reasoning links.
The three facts for a domain must be distinct and collectively useful.
Mark which construction ideas use each
fact with values from question, correct, missing_domain_knowledge,
parallel_knowledge, and incorrect_domain_relation. Explain why each fact is
necessary in one concise sentence. Do not invent a fact merely to fill a slot.

Return only this JSON object:
{
  "required_key_facts": {
    "domain_a": [
      {"key_fact": "specific phrase", "used_by": ["question", "correct"], "necessity": "Why it is needed."},
      {"key_fact": "specific phrase", "used_by": ["correct", "missing_domain_knowledge"], "necessity": "Why it is needed."},
      {"key_fact": "specific phrase", "used_by": ["question", "parallel_knowledge"], "necessity": "Why it is needed."}
    ]
  }
}

## 输出与保存 / Response and Saved Record

模型响应只有 `required_key_facts`。程序继续传递原始样本、key facts 和完整构造思路，并更新本步骤模型名。`used_by` 中用 `question` 表示问题构造思路。

The model returns only required_key_facts. The program carries forward the original sample, key facts, and complete construction ideas and updates the model name. The question-construction idea is identified by question in used_by.
