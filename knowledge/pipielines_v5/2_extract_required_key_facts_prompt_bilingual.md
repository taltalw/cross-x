# 融合领域知识需求提示词 / Required Key Facts Prompt

用于 v4 第 2 步的模板对照。包含中文语义模板、脚本实际使用的完整英文系统模板，以及输入字段介绍。运行方法见 [步骤说明](2_extract_required_key_facts.md)。

脚本：`2_extract_required_key_facts.py`；系统提示词变量：`SYSTEM_PROMPT`。中文部分用于解释模板语义，实际请求使用英文模板，要求模型生成英文内容；JSON 字段名和枚举值在中英文中保持一致。

For presentation and comparison of step 2 in v4. The Chinese section explains the template; the English system prompt is copied from the script. Runtime output is English, and JSON keys and enum values are unchanged between languages.

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
| `question_plan` | 步骤 1 的简短问题构造思路 | Brief question-construction idea from step 1 |
| `answer_plans` | 步骤 1 的四类答案构造思路 | Four answer-construction ideas from step 1 |
| `answer_plan_types` | 四类答案的固定英文标识列表 | Fixed list of the four answer-type identifiers |

## 领域选择与数量 / Domain Selection and Count

第 1 步只指定 `--domain-count N`，由模型结合原子样本和 key facts，从其余六个候选领域中选择一个合适的组合。N 沿用原版定义，包含源领域：N=3 时选择两个新增领域，总共三个领域。不再使用 `--fusion-domains` 参数。

模型选择的领域保存为 `fusion_domains`，每条样本可以不同。第 2–4 步从记录读取它们；这些步骤的 `--domain-count` 是可选的一致性校验参数，不重新指定领域。领域数不改变四类答案的约定。

Step 1 takes only --domain-count N. Using the atomic sample and its key facts, the model selects one suitable combination from the other six candidate domains. N includes the source domain: N=3 means two additional domains and three total. There is no --fusion-domains option.

The selected domains are saved as fusion_domains and can differ between samples. Steps 2–4 read them from each record; their optional --domain-count argument checks consistency rather than selecting domains. Domain count does not change the four answer types.

# 中文模板

提取构造跨领域问题及四个选项所需的外部知识。

输入包含原始原子样本、其 key facts、源领域、选定的 `fusion_domains`、问题构造思路（`question_plan`）和四类答案构造思路（`answer_plans`）。

任务：

1. 对 `fusion_domains` 中每个领域，提取恰好三个简短的英文知识点短语，用于构造问题及四个选项。
2. 在 `necessity` 中用一句简短的话解释每项知识为什么需要。

要求：

- 覆盖问题与答案思路实际需要的知识，包括支撑跨领域推理联系的知识。
- 每项 `key_fact` 应是该领域的具体概念、机制、规则、条件或关系；同一领域的三项需求要互不重复且共同有用，不要为凑数编造知识。
- 沿用步骤 0 的关键词风格：每项 `key_fact` 用几个英文词表达，不写完整句子；优先具体、有信息量的短语。解释写在 `necessity`，不要放进 `key_fact`。
- 不要输出完整问题、泛泛的领域名称或属于其他领域的事实。
- 只返回英文 JSON 对象；按实际 `fusion_domains` 为每个领域提供恰好三项，下方 `fusion_domain` 是领域标识占位符。

```json
{
  "required_key_facts": {
    "fusion_domain": [
      {"key_fact": "具体知识短语1", "necessity": "为什么需要这项知识。"},
      {"key_fact": "具体知识短语2", "necessity": "为什么需要这项知识。"},
      {"key_fact": "具体知识短语3", "necessity": "为什么需要这项知识。"}
    ]
  }
}
```

# English Template

Identify the external knowledge needed to construct a cross-domain
question and its four answer choices.

The input contains an original atomic sample, its key facts, the source domain,
the chosen fusion_domains, a question-construction idea (question_plan), and
four answer-construction ideas (answer_plans).

Tasks:
1. For each domain in fusion_domains, identify exactly three short English
   key-fact phrases needed to construct the question and four answer choices.
2. Explain in one concise sentence why each key fact is needed in necessity.

Requirements:
- Cover the knowledge needed by question_plan and answer_plans, including
  their cross-domain reasoning links.
- Each key_fact must name a concrete concept, mechanism, rule, condition, or
  relationship from its fusion domain. The three facts for a domain must be
  distinct and collectively useful; do not invent a fact just to fill a slot.
- Follow the step-0 key-fact style: use a few English words per key_fact, not
  sentences. Prefer specific, informative phrases over broad domain labels.
  Put explanations only in necessity, not in key_fact.
- Do not write the complete question, generic domain labels, or facts belonging
  to another domain.
- Return only an English JSON object in this format, with exactly three entries
  for every domain in fusion_domains:
{
  "required_key_facts": {
    "fusion_domain": [
      {"key_fact": "specific phrase", "necessity": "Why it is needed."},
      {"key_fact": "specific phrase", "necessity": "Why it is needed."},
      {"key_fact": "specific phrase", "necessity": "Why it is needed."}
    ]
  }
}

Example:
- input
{
  "source_domain": "mathematics",
  "sample": {"prompt": "Calculate the area of a circle of radius r.", "completion": "pi * r**2"},
  "key_facts": ["circle area", "pi times radius squared"],
  "fusion_domains": ["computer_science"],
  "question_plan": "Write a Python function that calculates a circle's area from its radius and returns the result, assuming math is imported and the radius is positive.",
  "answer_plans": [
    {"type": "correct", "missing_domain": null, "plan": "Compute pi times the radius squared and return the computed area."},
    {"type": "missing_domain_knowledge", "missing_domain": "mathematics", "plan": "Return the radius squared while omitting the required factor pi."},
    {"type": "parallel_knowledge", "missing_domain": null, "plan": "Compute the correct area expression but return the radius instead of the computed value."},
    {"type": "incorrect_domain_relation", "missing_domain": null, "plan": "Square the product of pi and the radius, applying the square to pi as well as the radius."}
  ],
  "answer_plan_types": ["correct", "missing_domain_knowledge", "parallel_knowledge", "incorrect_domain_relation"]
}

- output
{
  "required_key_facts": {
    "computer_science": [
      {"key_fact": "Python return statement", "necessity": "The area expression must become the function's returned value rather than an unused computation."},
      {"key_fact": "math.pi constant", "necessity": "The function needs a Python expression for the mathematical factor pi."},
      {"key_fact": "Python exponentiation", "necessity": "The code must square the radius without also squaring pi."}
    ]
  }
}

## 输出与保存 / Response and Saved Record

模型响应只有 `required_key_facts`，每项包含 `key_fact` 和 `necessity`。程序继续传递原始样本、key facts 和完整构造思路，并更新本步骤模型名。

The model returns only required_key_facts, with key_fact and necessity in each entry. The program carries forward the original sample, key facts, and complete construction ideas and updates the model name.
