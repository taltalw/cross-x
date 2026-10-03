# 融合问题生成提示词 / Fusion Question Generation Prompts

v4 第 4 步先用 `SCREEN_PROMPT` 从检索结果选样本并调整 plan，再对可行方案用未修改的 `SYSTEM_PROMPT` 分别生成 `easy`、`medium`、`hard` 三道题。以下英文模板与脚本中的提示词一致；中文部分说明其用途。

Step 4 selects samples and revises the plan with `SCREEN_PROMPT`, then calls the unchanged `SYSTEM_PROMPT` once for each difficulty of a feasible plan. The English templates below match the script.

## 证据筛选 / Evidence Screening

输入包含源样本、旧构造思路和按领域排列的检索问答。旧思路仅作参考；模型从检索样本中选择能自然参与同一道跨领域题的材料，返回调整后的构题思路、四类答案思路及知识需求。无法利用所有新增领域组成共同任务时，返回 `feasible: false`，该方案不进入生成。

程序检查所选问答是否来自对应领域，以及可行时每个领域是否至少有一条样本、四类答案和三个需求的结构是否有效。组合是否自然由模型判断。

### English Screening Template

Find a natural cross-domain question that can be constructed
from the original sample and the retrieved samples in every fusion domain.
The existing question_plan and answer_plans are optional starting points,
not requirements that the retrieved samples must match.

Tasks:
1. Select the exact retrieved samples that can contribute necessary knowledge
   to one joint question with the source sample. Use every fusion domain.
2. If such a question is feasible, revise question_plan and all four
   answer_plans to fit the selected samples. Preserve the source sample's core
   knowledge and the chosen fusion_domains.
3. Rewrite required_key_facts to describe the knowledge actually used from
   each fusion domain: exactly three short keyword phrases and a brief
   necessity for each.

Requirements:
- Judge facts from the original prompt and completion of each sample. Do not
  invent facts or add an unrelated domain merely to force a combination.
- Do not reject a useful sample because it does not support the old plan;
  adjust the plan to what the retrieved material can naturally support.
- Set feasible to false only when the available samples cannot support one
  coherent joint task using every fusion domain. Then use null for all plan
  fields and empty selected_samples lists.
- List only exact supplied samples from their own domains. Keep each key_fact
  to a few English words, not a sentence; put explanations in necessity.
- Return only this English JSON object:
{
  "feasible": true,
  "reason": "Why the selected samples form one joint task, or why none do.",
  "selected_samples": {
    "fusion_domain": [{"prompt": "Original question", "completion": "Original answer"}]
  },
  "question_plan": "Brief revised joint question idea.",
  "answer_plans": [
    {"type": "correct", "missing_domain": null, "plan": "..."},
    {"type": "missing_domain_knowledge", "missing_domain": "participating domain", "plan": "..."},
    {"type": "parallel_knowledge", "missing_domain": null, "plan": "..."},
    {"type": "incorrect_domain_relation", "missing_domain": null, "plan": "..."}
  ],
  "required_key_facts": {
    "fusion_domain": [
      {"key_fact": "short phrase", "necessity": "Why needed."},
      {"key_fact": "short phrase", "necessity": "Why needed."},
      {"key_fact": "short phrase", "necessity": "Why needed."}
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
  "question_plan": "Reverse a string before calculating a circle's area.",
  "answer_plans": [
    {"type": "correct", "missing_domain": null, "plan": "Reverse the string and calculate the area."},
    {"type": "missing_domain_knowledge", "missing_domain": "mathematics", "plan": "Omit pi."},
    {"type": "parallel_knowledge", "missing_domain": null, "plan": "Keep the two computations separate."},
    {"type": "incorrect_domain_relation", "missing_domain": null, "plan": "Apply the string operation to the radius."}
  ],
  "retrieved_samples": {
    "computer_science": [
      {"prompt": "What do return, math.pi, and ** do in Python?", "completion": "return sends back a value; math.pi is pi; ** exponentiates."}
    ]
  }
}

- output
{
  "feasible": true,
  "reason": "The Python sample can express and return the circle-area calculation.",
  "selected_samples": {
    "computer_science": [
      {"prompt": "What do return, math.pi, and ** do in Python?", "completion": "return sends back a value; math.pi is pi; ** exponentiates."}
    ]
  },
  "question_plan": "Write a Python function that returns the area of a circle from its radius.",
  "answer_plans": [
    {"type": "correct", "missing_domain": null, "plan": "Return pi times radius squared."},
    {"type": "missing_domain_knowledge", "missing_domain": "mathematics", "plan": "Return radius squared without pi."},
    {"type": "parallel_knowledge", "missing_domain": null, "plan": "Compute the area but return the radius."},
    {"type": "incorrect_domain_relation", "missing_domain": null, "plan": "Square pi with the radius."}
  ],
  "required_key_facts": {
    "computer_science": [
      {"key_fact": "Python return statement", "necessity": "Return the computed value."},
      {"key_fact": "math.pi constant", "necessity": "Represent pi in code."},
      {"key_fact": "Python exponentiation", "necessity": "Square the radius."}
    ]
  }
}

## 题目生成 / Question Generation

通过筛选后，模型按指定 `difficulty` 生成一题。提示词只要求遵循难度标签，不定义简单、中等、困难的具体标准。题干和选项尽可能简洁，不加入额外推理步骤；解释字段可说明正确理由。程序在每条结果中添加 `difficulty`。

The generation request includes the requested difficulty, revised plan and requirements, and only the selected samples. The saved row keeps all retrieved question-answer samples.

### English Generation Template

Construct one cross-domain multiple-choice question from
the supplied plan and evidence-supported retrieved samples.

The input includes the original atomic sample and key facts, fusion_domains,
question_plan, answer_plans, required_key_facts, retrieved_samples, and the
requested difficulty. The source domain is represented by the original sample;
the fusion domains are represented by retrieved samples.

Tasks:
1. Follow the question_plan to create one natural joint task using the original
   sample's core knowledge and every chosen fusion domain.
2. Create four distinct options: one correct answer and three distractors of
   types missing_domain_knowledge, parallel_knowledge, and
   incorrect_domain_relation. The correct option may be A, B, C, or D.
3. Explain the correct answer, analyze each distractor, and list at least one
   used sample from every fusion domain in used_samples.

Requirements:
- Write the question at the requested difficulty. Do not define difficulty
  levels or put the difficulty label in the question or options.
- Keep the question and answer options as concise as possible while including
  the conditions needed to solve it. Put no extra reasoning steps in the
  question or options; use explanation for reasoning.
- Use the supplied sample text as evidence. Do not invent domain facts, add
  domains, or replace the joint task with another task.
- If the plan needs a substantive adjustment, describe it in plan_adjustment;
  otherwise use an empty string.
- Return only an English JSON object in this format:

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
  "used_samples": {"fusion_domain": [{"prompt": "Original question", "completion": "Original answer"}]},
  "plan_adjustment": ""
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
  "required_key_facts": {
    "computer_science": [
      {"key_fact": "Python function return statement", "necessity": "The function must return the area."},
      {"key_fact": "Python math module pi constant", "necessity": "The expression needs pi."},
      {"key_fact": "Python exponentiation and parentheses", "necessity": "Only the radius is squared."}
    ]
  },
  "retrieved_samples": {
    "computer_science": [
      {"prompt": "What do return, math.pi, **, and parentheses do in Python?", "completion": "return sends back a value; math.pi is pi; ** exponentiates; parentheses group operations."}
    ]
  },
  "option_count": 4,
  "difficulty": "easy"
}

- output
{
  "question": "With math imported and r > 0, which function returns a circle's area?",
  "options": {
    "A": "def area(r): return math.pi * r**2",
    "B": "def area(r): return r**2",
    "C": "def area(r): math.pi * r**2; return r",
    "D": "def area(r): return (math.pi * r)**2"
  },
  "answer": "A",
  "explanation": "The function returns pi times the radius squared.",
  "distractor_analysis": [
    {"option": "B", "type": "missing_domain_knowledge", "missing_domain": "mathematics", "reason": "It omits pi."},
    {"option": "C", "type": "parallel_knowledge", "missing_domain": null, "reason": "It computes the area but returns the radius."},
    {"option": "D", "type": "incorrect_domain_relation", "missing_domain": null, "reason": "It squares pi along with the radius."}
  ],
  "used_samples": {
    "computer_science": [
      {"prompt": "What do return, math.pi, **, and parentheses do in Python?", "completion": "return sends back a value; math.pi is pi; ** exponentiates; parentheses group operations."}
    ]
  },
  "plan_adjustment": ""
}

## 输出与保存 / Saved Records

每个可行方案写入三条 JSONL，分别标注 `difficulty: easy`、`medium`、`hard`，并保存调整后的 plan 和知识需求。不可行方案不写入题目文件；脚本在标准错误输出中记录跳过原因，并在报告中统计 `processed`、`skipped`、`generated`。`--num` 限制读取的方案数，而非生成题数。

Each passing plan yields three JSONL records. Rejected plans produce no question records. The script logs skip reasons to stderr and reports processed plans, skipped plans, and generated questions.
