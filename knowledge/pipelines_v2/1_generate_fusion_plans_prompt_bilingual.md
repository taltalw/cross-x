# 融合问题与四类答案构造思路提示词 / Fusion Question and Four Answer Construction Ideas Prompt

用于 `pipelines_v2` 第 1 步的 presentation 与模板对照。包含中文语义模板、脚本实际使用的完整英文系统模板，以及输入字段介绍。运行方法见 [步骤说明](1_generate_fusion_plans.md)。

脚本：`1_generate_fusion_plans.py`；系统提示词变量：`SYSTEM_PROMPT`。中文部分用于解释模板语义，实际请求使用英文模板，要求模型生成英文内容；JSON 字段名和枚举值在中英文中保持一致。

For presentation and comparison of step 1 in pipelines_v2. The Chinese section explains the template; the English system prompt is copied from the script. Runtime output is English, and JSON keys and enum values are unchanged between languages.

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

你负责为一个跨领域问题设计简洁的构题思路，用于指导后续的外部知识提取、样本检索，以及问题和四个答案选项的生成。

输入包含原始原子样本、其 key facts、源领域、候选领域列表和期望的总领域数 `domain_count`。请结合样本和 key facts，思考可以与哪些领域构造跨领域问题，从候选领域中选择恰好 `domain_count - 1` 个不同领域，与源领域组成一个组合，并在 `fusion_domains` 中返回。所选领域不能包含源领域；选择应基于专业知识的必要贡献，而非领域名称的泛泛关联。根据所选领域和源领域，设计一个融合了多领域知识的联合任务。跨领域问题需要每个参与领域的专业知识围绕同一个任务目标共同发挥作用。仅更换背景、添加术语或拼接无关问题，不构成有效融合。

保留原始样本的核心知识。不要编造支持性事实，应指出后续检索样本需要提供什么知识。

提供简洁的问题构造思路和四类答案构造思路：

1. `correct`：正确整合所有领域及其必要关系。
2. `missing_domain_knowledge`：遗漏一个参与领域中的某项必要知识，同时正确使用其他领域的知识。
3. `parallel_knowledge`：分别正确使用各领域事实，但未考虑它们之间必要的相互作用。
4. `incorrect_domain_relation`：使用相关事实，却错误连接领域间关系，例如颠倒因果或将条件应用到错误结果上。

使用 `question_plan` 记录问题构造思路，使用 `answer_plans` 记录四类答案构造思路。简要说明联合任务目标、关键条件、各领域的贡献及其推理联系。每个说明字段用一句简短的话表达，每类答案构造思路用一至两句话表达。不要写出完整题目或最终选项。后续步骤将生成恰好四个选项，正确答案可以位于任意位置。实际输出使用英文，只返回指定的 JSON 对象。

输出结构如下。`fusion_domains` 应展开为恰好 N−1 个所选候选领域，`domain_roles` 为全部 N 个参与领域各提供一项。下方只展示单项结构。

```json
{
  "fusion_domains": ["所选候选领域标识"],
  "question_plan": {
    "objective": "一个联合任务目标。",
    "conditions": "完成求解所需的关键给定信息或条件。",
    "domain_roles": [
      {"domain": "实际领域标识", "role": "必要贡献", "knowledge_needed": "所需的具体知识"}
    ],
    "reasoning_link": "各领域贡献如何相互作用并共同导向一个答案。"
  },
  "answer_plans": [
    {"type": "correct", "missing_domain": null, "plan": "正确综合各领域知识的答案构造思路。"},
    {"type": "missing_domain_knowledge", "missing_domain": "一个参与领域", "plan": "遗漏该领域某项必要知识的错误答案思路。"},
    {"type": "parallel_knowledge", "missing_domain": null, "plan": "仅并列各领域结论的错误答案思路。"},
    {"type": "incorrect_domain_relation", "missing_domain": null, "plan": "错误连接领域关系的答案思路。"}
  ]
}
```

# English Template

You design a concise construction idea for a cross-domain question,
to guide subsequent external-knowledge extraction, sample retrieval, and
generation of the question and its four answer options.

The input contains an original atomic sample, its key facts, the source domain,
a list of candidate domains, and the requested total domain_count.
Based on the sample and its key facts, consider which additional domains can
participate in one cross-domain question. Choose exactly domain_count - 1 distinct
candidate domains, excluding the source domain, and return one combination in
fusion_domains. The total includes the source domain. Select domains for their
necessary specialized knowledge, not generic associations with domain names.
Using the chosen domains and the source domain, design one joint task that
integrates knowledge from multiple domains. A cross-domain question
requires specialized knowledge from every participating domain to work together
toward the same task objective. Merely changing the setting, adding terminology,
or concatenating unrelated questions does not constitute valid fusion.
Retain the original sample's core knowledge. Do not invent supporting facts:
identify what must be provided by later retrieved samples.

Provide a concise question-construction idea and four answer-construction ideas:
1. correct: combine all domains and their necessary relationships correctly;
2. missing_domain_knowledge: omit one specific necessary fact from one
   participating domain while using the other domains correctly;
3. parallel_knowledge: use domain facts correctly in isolation but fail to model
   their necessary interaction;
4. incorrect_domain_relation: use relevant facts but connect domains incorrectly,
   such as reversing causality or applying a condition to the wrong result.

Use question_plan to record the question-construction idea and answer_plans to
record the four answer-construction ideas. Briefly state the joint objective,
essential conditions, each domain's contribution, and their reasoning link.
Keep each explanatory field to one short sentence and each answer-construction
idea to one or two sentences. Do not write the complete question or final options.
The later stage will create exactly four options and may place the correct
option anywhere.
Return English text and only the requested JSON object.

Required JSON structure (expand fusion_domains and domain_roles to the requested count):
{
  "fusion_domains": ["selected_candidate_domain"],
  "question_plan": {
    "objective": "One joint task objective.",
    "conditions": "Essential givens or conditions needed to solve it.",
    "domain_roles": [
      {"domain": "exact domain", "role": "necessary contribution", "knowledge_needed": "specific knowledge needed"}
    ],
    "reasoning_link": "How the domain contributions interact toward one answer."
  },
  "answer_plans": [
    {"type": "correct", "missing_domain": null, "plan": "..."},
    {"type": "missing_domain_knowledge", "missing_domain": "one participating domain", "plan": "..."},
    {"type": "parallel_knowledge", "missing_domain": null, "plan": "..."},
    {"type": "incorrect_domain_relation", "missing_domain": null, "plan": "..."}
  ]
}

## 输出与保存 / Response and Saved Record

模型响应包含所选 `fusion_domains`、`question_plan` 和 `answer_plans`。程序校验领域数量、去重、排除源领域，以及各领域在构造思路中的覆盖，然后保存源样本、key facts、领域总数和本步骤模型名。

The model returns fusion_domains, question_plan, and answer_plans. The program validates domain count, uniqueness, exclusion of the source, and coverage in the construction ideas, and saves the source sample, key facts, total count, and model name.
