# 融合问题与四类答案构造思路提示词 / Fusion Question and Four Answer Construction Ideas Prompt

用于 v5 第 1 步的模板对照。包含中文语义说明、脚本实际使用的完整英文系统模板，以及输入字段介绍。运行方法见 [步骤说明](1_generate_fusion_plans.md)。

脚本：`1_generate_fusion_plans.py`；系统提示词变量：`SYSTEM_PROMPT`。中文部分用于解释模板语义，实际请求使用英文模板，要求模型生成英文内容；JSON 字段名和枚举值在中英文中保持一致。

For presentation and comparison of step 1 in v5. The Chinese section explains the template; the English system prompt is copied from the script. Runtime output is English, and JSON keys and enum values are unchanged between languages.

## 消息组织 / Message Structure

`system` 消息使用下方英文 `SYSTEM_PROMPT`。每条样本的数据单独组织为 JSON 对象，经 `json.dumps(..., ensure_ascii=False)` 序列化后写入 `user` 消息；数据没有直接插入 system 模板。

The system message contains the English SYSTEM_PROMPT below. Per-sample data is serialized as JSON in a separate user message; it is not interpolated into the system prompt.

| 用户消息字段 / User field | 中文说明 | English description |
| --- | --- | --- |
| `source_domain` | 源领域 A | Source domain A |
| `sample` | 完整原始问答 | Original question and answer |
| `key_facts` | 源样本的 2–3 个关键词组 | Two or three key-fact phrases from the source sample |
| `candidate_domains` | 除源领域外的六个候选领域及其介绍，由模型选择 | Names and descriptions of the six domains other than the source, for model selection |
| `domain_count` | 包含源领域的总领域数 | Total number of domains including the source |

## 领域选择与数量 / Domain Selection and Count

第 1 步只指定 `--domain-count N`，由模型结合原子样本和 key facts，从其余六个候选领域中选择一个合适的组合。N 沿用原版定义，包含源领域：N=3 时选择两个新增领域，总共三个领域。不再使用 `--fusion-domains` 参数。

模型选择的领域保存为 `fusion_domains`，每条样本可以不同。第 2–4 步从记录读取它们；这些步骤的 `--domain-count` 是可选的一致性校验参数，不重新指定领域。领域数不改变四类答案的约定。

Step 1 takes only --domain-count N. Using the atomic sample and its key facts, the model selects one suitable combination from the other six candidate domains. N includes the source domain: N=3 means two additional domains and three total. There is no --fusion-domains option.

The selected domains are saved as fusion_domains and can differ between samples. Steps 2–4 read them from each record; their optional --domain-count argument checks consistency rather than selecting domains. Domain count does not change the four answer types.

## 候选领域介绍 / Candidate Domain Descriptions

| 标识 / Identifier | 中文介绍 | English description |
| --- | --- | --- |
| `medical` | 医学：生理、疾病、诊断、治疗、药理和公共卫生。 | Medicine: physiology, disease, diagnosis, treatment, pharmacology, and public health. |
| `legal` | 法律：法律规则、权利、义务、合同、责任、程序和合规。 | Law: legal rules, rights, obligations, contracts, liability, procedure, and compliance. |
| `financial` | 金融：货币、银行、投资、资产定价、企业财务、会计和风险。 | Finance: money, banking, investment, asset pricing, corporate finance, accounting, and risk. |
| `mathematics` | 数学：代数、几何、微积分、概率、统计、优化和建模。 | Mathematics: algebra, geometry, calculus, probability, statistics, optimization, and modeling. |
| `computer_science` | 计算机科学：算法、数据结构、网络、操作系统、数据库和安全。 | Computer science: algorithms, data structures, networks, operating systems, databases, and security. |
| `geography` | 地理：地貌、地质、气候、水文、空间分布、资源和人地关系。 | Geography: landforms, geology, climate, hydrology, spatial distributions, resources, and human-environment relations. |
| `chemistry` | 化学：物质、化学反应、机理、分析方法和化学安全。 | Chemistry: matter, chemical reactions, mechanisms, analytical methods, and chemical safety. |

程序将除源领域以外的六个候选领域及其介绍放入用户消息，尚未指定哪些领域参与。

The user message includes the six candidate domains other than the source and their descriptions; participating additional domains have not yet been selected.

# 中文模板

为一个自然的跨领域问题设计简洁的构题思路。题目应围绕一个需要多领域知识共同完成的任务，四个选项包含一个正确答案和三个干扰项。

输入包含原始原子样本、其 key facts、源领域、候选领域列表和总领域数 `domain_count`。

任务：

1. 结合样本与 key facts，考虑哪些额外领域可以参与构题，从候选领域中选择恰好 `domain_count - 1` 个不同领域，不包含源领域。
2. 用所选领域和源领域设计一个融合多领域知识的联合任务，提供简要的问题构造思路。
3. 思考四个选项的构造，提供四类答案构造思路：

   - `correct`：正确结合领域知识并回答联合任务。
   - `missing_domain_knowledge`：遗漏一个指定领域的必要知识。
   - `parallel_knowledge`：包含相关知识，但没有把它们连接到答案。
   - `incorrect_domain_relation`：错误连接领域知识。

要求：构造自然的问题，避免生搬硬造、生硬融合。不要写完整题目或最终选项；后续步骤会生成恰好四个选项，正确答案可以位于任意位置。只返回英文 JSON 对象，字段格式见下方。英文模板末尾的圆面积示例仅示范构造思路。

输出结构如下。`fusion_domains` 应包含恰好 N−1 个所选候选领域，`question_plan` 是一句简要的联合任务构造思路。

```json
{
  "fusion_domains": ["所选候选领域标识"],
  "question_plan": "一个联合任务的简要构造思路。",
  "answer_plans": [
    {"type": "correct", "missing_domain": null, "plan": "正确综合各领域知识的答案构造思路。"},
    {"type": "missing_domain_knowledge", "missing_domain": "一个参与领域", "plan": "遗漏该领域某项必要知识的错误答案思路。"},
    {"type": "parallel_knowledge", "missing_domain": null, "plan": "仅并列各领域结论的错误答案思路。"},
    {"type": "incorrect_domain_relation", "missing_domain": null, "plan": "错误连接领域关系的答案思路。"}
  ]
}
```

# English Template

Design a concise idea for constructing a natural cross-domain question.
The question should ask for one joint task that integrates knowledge from
multiple domains; its four answer choices should contain one correct answer and three distractor answers.

The input contains an original atomic sample, its key facts, the source domain,
a list of candidate domains, and the requested total domain_count.

Tasks:
1. Based on the sample and its key facts, consider which additional domains can
   participate in cross-domain question construction. Choose exactly domain_count - 1 distinct
   candidate domains, excluding the source domain.
2. Using the chosen domains and the source domain, design one joint task that
   integrates knowledge from multiple domains. Provide a brief question-construction
   idea as a single string in question_plan.
3. Consider how to construct four answer choices. Provide four answer-construction ideas:
   - correct: combine the domain knowledge correctly and answer the joint task;
   - missing_domain_knowledge: omit a necessary fact from one named domain;
   - parallel_knowledge: include the relevant knowledge but fail to connect it
     to the answer;
   - incorrect_domain_relation: connect the domain knowledge incorrectly.

Requirements:
- Construct a natural question; avoid forced or awkward combinations of domains.
- Do not write the complete question or final options. The later stage will
  create exactly four options and may place the correct option anywhere.
- Return only an English JSON object in the following format. Include exactly
  domain_count - 1 fusion_domains:
{
  "fusion_domains": ["selected_candidate_domain"],
  "question_plan": "Brief idea for one joint task integrating the chosen domains.",
  "answer_plans": [
    {"type": "correct", "missing_domain": null, "plan": "..."},
    {"type": "missing_domain_knowledge", "missing_domain": "one participating domain", "plan": "..."},
    {"type": "parallel_knowledge", "missing_domain": null, "plan": "..."},
    {"type": "incorrect_domain_relation", "missing_domain": null, "plan": "..."}
  ]
}

example
-input
{
  "source_domain": "mathematics",
  "sample": {"prompt": "Calculate the area of a circle of radius r.", "completion": "pi * r**2"},
  "key_facts": ["circle area", "pi times radius squared"],
  "candidate_domains": [
    {"name": "medical", "description": "Medicine: physiology, disease, diagnosis, treatment, pharmacology, and public health."},
    {"name": "legal", "description": "Law: legal rules, rights, obligations, contracts, liability, procedure, and compliance."},
    {"name": "financial", "description": "Finance: money, banking, investment, asset pricing, corporate finance, accounting, and risk."},
    {"name": "computer_science", "description": "Computer science: algorithms, data structures, networks, operating systems, databases, and security."},
    {"name": "geography", "description": "Geography: landforms, geology, climate, hydrology, spatial distributions, resources, and human-environment relations."},
    {"name": "chemistry", "description": "Chemistry: matter, chemical reactions, mechanisms, analytical methods, and chemical safety."}
  ],
  "domain_count": 2
}

-output
{
  "fusion_domains": ["computer_science"],
  "question_plan": "Write a Python function that calculates a circle's area from its radius and returns the result, assuming math is imported and the radius is positive.",
  "answer_plans": [
    {"type": "correct", "missing_domain": null, "plan": "Compute pi times the radius squared and return the computed area."},
    {"type": "missing_domain_knowledge", "missing_domain": "mathematics", "plan": "Return the radius squared while omitting the required factor pi."},
    {"type": "parallel_knowledge", "missing_domain": null, "plan": "Compute the correct area expression but return the radius instead of the computed value."},
    {"type": "incorrect_domain_relation", "missing_domain": null, "plan": "Square the product of pi and the radius, applying the square to pi as well as the radius."}
  ]
}

## 输出与保存 / Response and Saved Record

模型响应包含所选 `fusion_domains`、简短文本 `question_plan` 和 `answer_plans`。程序校验领域数量、去重、排除源领域、构题思路非空及四类答案构造思路，然后保存源样本、key facts、领域总数和本步骤模型名。

The model returns fusion_domains, a nonempty question_plan string, and answer_plans. The program validates domain count, uniqueness, exclusion of the source, and all four answer-plan types, then saves the source sample, key facts, total count, and model name.
