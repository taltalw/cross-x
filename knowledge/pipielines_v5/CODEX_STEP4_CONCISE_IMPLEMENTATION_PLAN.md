# Codex 执行任务：将 v4 第 4 步改为简洁、单目标的跨领域题目生成

## 0. 任务与实施原则

请直接修改本地仓库中的代码、提示词、文档和测试，而不是仅提出建议。

本次目标：保留 Instance-Conditioned Need-First 的前置流程，直接读取已有第 3 步检索结果，只在第 4 步把“展开多领域计划、输出完整报告”改为“围绕一个最终回答对象，生成简洁但仍依赖所有参与领域的题目”。

本任务是针对现有 v4 的工程修改，不是复现 XDomainBench。本文件中的长度预算、质检方式及新字段均是本项目的设计选择，不得在文档中称为 XDomainBench 的官方参数或已验证结论。

**成功标准不是题目越短越好，而是在不损害可解性、跨领域依赖和证据支持的前提下，减少显式子任务、重复背景和报告型选项。**

上传源码的目录实际拼写为 `pipielines_v4`。先定位本地 `4_generate_fusion_question.py`；常见路径为 `knowledge/pipielines_v4/`，不要根据聊天中的拼写变体重命名目录。本文件以下以 `<PIPELINE_DIR>` 代指该目录。

如本地已经应用之前的 `pipelines_v4_step4_concise_patch.zip`，先检查差异，再按本文件补齐；不要重复叠加生成、审查或随机打乱逻辑。之前的补丁是参考实现，不是必须逐行覆盖的目标。本规范特别明确了短选项错误标签的解释边界、稳定 ID、代码格式和运行输出隔离。

## 1. 先检查真实实现，不要重写整个项目

请首先阅读：

```text
<PIPELINE_DIR>/4_generate_fusion_question.py
<PIPELINE_DIR>/_pipeline_common.py
<PIPELINE_DIR>/4_generate_fusion_question.md
<PIPELINE_DIR>/4_generate_fusion_question_prompt_bilingual.md
<PIPELINE_DIR>/run_4.sh
<PIPELINE_DIR>/run_config.sh
<PIPELINE_DIR>/tests/test_fusion_v2_stages.py
<PIPELINE_DIR>/tests/test_serial_shell.py
```

并沿 import 找到 `knowledge.pipelines._knowledge_search_common.JSONAPI`，确认其重试、校验回调和错误行为。不要另写一套 HTTP 客户端，也不要为适配附件中的目录结构修改全项目导入路径。

上传的原始 v4 有以下特征；本地版本不一致时以本地源码为准，并在交付说明中列出差异：

| 位置 | 已有行为 | 本次需要补上的能力 |
|---|---|---|
| `SCREEN_PROMPT` | 已允许依据检索证据调整原始计划 | 强制收缩到一个最终目标，并明确各领域的必要作用 |
| `validate_screening()` | 检查领域覆盖、所选样本归属、计划和 required_key_facts | 验证新的 compact_blueprint；保留旧样本引用约束 |
| `SYSTEM_PROMPT` | 已有“尽量简洁”的文字要求 | 增加答案形式、长度预算、反报告化约束 |
| `process()` | 筛选一次，依次生成 easy/medium/hard | 加入硬检查、打乱、语义审查和有限定向重写 |
| `validate_generation()` | 校验结构、错误类型和引用 | 第 4 步局部加强错误选项覆盖检查，并保留代码换行缩进 |
| `run_4.sh` / `run_config.sh` | 输入、输出共用 V4_ROOT | 新增独立运行入口，旧第 3 步输入与新第 4 步输出分开 |

不要把原代码描述成“不允许调整原计划”或“完全没有简洁要求”。问题是这些要求尚未落实为单目标结构与可执行检查。

## 2. 修改范围

### 2.1 允许修改或新增

| 文件 | 要求 |
|---|---|
| `4_generate_fusion_question.py` | 修改第 4 步主流程；保留原 CLI 参数和主要输入输出接口 |
| `_concise_prompts.py` | 新增或复用；集中保存 SCREEN_PROMPT、SYSTEM_PROMPT、AUDIT_PROMPT、REPAIR_PROMPT |
| `_concise_fusion.py` | 新增或复用；放置纯函数：预算、蓝图校验、局部生成校验、统计、ID、打乱、审查结果检查 |
| `tests/test_concise_fusion.py` | 增加离线单元测试和 mock API 流程测试 |
| `tests/test_fusion_v2_stages.py` | 仅调整第 4 步相关 mock 和断言，不删除上游测试 |
| `4_generate_fusion_question.md` | 更新运行方法、字段含义、失败行为及调用成本 |
| `4_generate_fusion_question_prompt_bilingual.md` | 同步实际提示词及中文解释 |
| `run_4_concise.sh` | 新增独立运行入口，不替换旧的 run_4.sh |
| `audit_step4_concise.py` | 新增离线统计与新旧对比脚本；不得发起模型调用 |

辅助文件数量可根据本地风格适当合并，不要搭建新的通用框架。

### 2.2 不得改变

不修改第 0–3 步算法、embedding、检索、已有领域列表、共享 JSONAPI、共享 `_pipeline_common.py` 的行为、旧运行脚本和旧结果文件。不要重新运行前面的步骤。

保留四选一、一个正确项和以下三类干扰项：

```text
missing_domain_knowledge
parallel_knowledge
incorrect_domain_relation
```

保留 easy / medium / hard 三个生成目标；同一计划最多产生三道合格题，不能强制凑齐。

保留原 `required_key_facts` schema：每个新增领域恰好三个不同的短语及其 necessity。这里的“三个短语”不是三个独立子问题；可以是同一必要概念的不同组成方面，但不能为了凑数写三个重复同义词或伪造知识需求。

不要根据旧 HANDOFF 中的历史候选领域扩展当前源码中的领域集合。所有领域从第 3 步输入记录读取并验证。

## 3. 新流程：只在原第 4 步内部调整

```text
读取、验证旧第 3 步记录
    ↓
原来的筛选调用：选择证据 + 调整计划 + 生成 compact_blueprint
    ↓
按 easy / medium / hard 分别生成候选
    ↓
原结构与引用校验 + 第 4 步新增硬检查
    ↓
程序化、可复现地打乱选项
    ↓
答案标签盲审（不向审查模型提供拟定答案及解释）
    ↓
合格 → 正式输出
不合格 → 最多定向重写一次 → 重新完整检查
仍不合格 → 仅写审计日志，不写正式题目文件
```

筛选同时生成蓝图，不新增一个单独的规划调用。不因第 4 步失败重新检索或偷偷替换领域。

保留原 `--num` 的含义：限制处理的输入计划数，不是限制最终题数。语义质量拒绝允许本组输出少于 `3 × num` 道题。

## 4. 筛选阶段：增加 compact_blueprint

### 4.1 收缩的是最终目标，不是参与领域

筛选模型可以修改 `question_plan`、`answer_plans` 和 `required_key_facts`，但必须保留源样本核心知识以及全部 `fusion_domains`。

每道题只有一个最终回答对象，例如一个数值、一个决策、一个短结论、一个表达式或一段局部代码。一个目标可以依赖多步推理和多个领域，不要求必须是一条线性依赖链；多个领域也可以共同约束同一决策。

以下不算真正的单目标：将“分别识别概念、计算三个结果、给出法律判断、输出完整排序轨迹”包装成一个名为 report 的对象。

不要通过改成“Which report is correct?”、删去问号或使用分号来形式上满足单目标要求。

### 4.2 新字段

在原筛选输出上增加以下字段。`answer_form` 为本规范新增的显式呈现约束；若沿用旧补丁，请同时更新校验及测试。

```json
{
  "compact_blueprint": {
    "target": "The single final result the item asks for.",
    "answer_form": "number | decision | short_text | expression | code",
    "dependency_summary": "How the participating domains jointly determine that result.",
    "domain_roles": {
      "source_domain_name": {
        "knowledge": "The source sample's core knowledge actually required.",
        "role": "How this knowledge contributes to the final result.",
        "removal_effect": "What becomes wrong or underdetermined without this knowledge."
      },
      "fusion_domain_name": {
        "knowledge": "The necessary knowledge supported by selected samples.",
        "role": "How this knowledge contributes to the final result.",
        "removal_effect": "What becomes wrong or underdetermined without this knowledge."
      }
    }
  }
}
```

实际 `answer_form` 是枚举中的单个字符串，不是带竖线的字符串。示例中的领域名替换为真实领域名。

`domain_roles` 必须恰好覆盖 `[source_domain, *fusion_domains]`；而 `selected_samples`、`required_key_facts` 仍只覆盖新增领域，不改变旧 schema。

蓝图仅为内部构造记录，不放进题干或选项。建议 `target` 不超过 20 个英文词，`dependency_summary` 不超过 70 个词，每个领域作用字段不超过 35 个词，防止内部蓝图再次变成报告计划；这些上限是可配置的工程初值。

保留现有引用规则：selected_samples 必须对应输入中该领域真实提供的 prompt/completion，不得改写引用、不跨领域引用、不仅凭标题声称有证据。

当不能构造自然、简洁且使用全部领域的任务时，`feasible=false`；各领域 selected_samples 为空列表，旧计划字段及 compact_blueprint 均为 null。记录明确原因，不增加一个装饰性领域勉强通过。

可以保留原 `validate_screening()`，另加 `validate_compact_screen()` 调用旧校验和蓝图校验；也可以局部扩展，但不要改变共享校验器。

### 4.3 SCREEN_PROMPT 的核心要求

用下列英文要求重写或补充原 SCREEN_PROMPT，同时保留其完整 JSON 输出 schema：

```text
Find one compact, evidence-supported cross-domain task using the source
sample's core knowledge and every chosen fusion domain.

The existing question_plan and answer_plans are optional starting points.
Prefer the smallest coherent final target supported by the available evidence,
not a shorter wording of an over-expanded multi-part task.

Select only necessary retrieved samples. Produce a compact_blueprint stating
one final target, a common answer form, and the necessary role of every domain,
including the source domain.

Multiple reasoning steps are allowed. Multiple independent requested outputs
are not. Do not hide a bundle of independent tasks inside a report, tuple,
checklist, or long code artifact.

Preserve the source knowledge and all chosen domains. A domain is not necessary
merely because its terminology, setting, or sample is mentioned. Explain which
inference or decision would fail without its knowledge.

Rewrite the plans and the three required-key-fact phrases per fusion domain
around this target. Three phrases do not mean three visible subquestions.
Do not pad the phrases with duplicated paraphrases or unsupported requirements.

Plan three concrete wrong outcomes corresponding to the retained error types.
If the evidence cannot support a natural joint target, return feasible=false.
Return only the required English JSON object.
```

## 5. 生成阶段：简洁题面，完整后台记录

### 5.1 题面规则

被测模型可见内容只包含 `question` 和四个 `options`，外加统一答题指令。答案、解释、检索样本、蓝图、错误类型和审查结果不得混入评测输入。

题干只写必要情境、数据、边界条件和一个最终问题。中间推理和知识归属放入 explanation。

四个选项必须回答同一个问题，采用同一种语义类型，优先使用短数值、短决策、表达式或局部代码片段。不能三个选项是数值，另一个是“虽然知道各领域知识但没有完成整合”。

公共条件与公共代码只写一次。较长公共代码可放题干，选项只给待补全的片段；不能把考查内容直接写进公共代码而使该领域失去必要性。

“单目标”不意味着允许所有正确答案一律压成一个词。保留解决歧义所需的单位、局部接口约定、适用范围、精度要求等。

对知识型 benchmark，不要把真正要测的通用知识规则、公式或桥接关系直接赠送到题干中。但题目特有的输入、非标准 API 约定和明确的局部前提必须给足。判断标准是：该信息是实例条件，还是本来需要模型掌握的被测知识。

不能仅以题面出现数学数字、法律名词或医学场景，就认为相应领域知识必不可少。通用算术或常识是否足以代表某领域，也要在蓝图和审查中说明。

### 5.2 SYSTEM_PROMPT 核心文本

实际提示词仍附上旧生成 JSON schema；以下是应加入的行为约束：

```text
Write one compact, single-target cross-domain multiple-choice item from the
compact_blueprint, revised plans, and selected evidence.

Ask for one final result. Keep all participating domains necessary for that
result. Do not expand the blueprint into a report, a list of independent
questions, or a complete worked solution.

The question must be self-contained for a model that has the tested domain
knowledge but cannot see the source samples or construction metadata. Include
necessary instance-specific conditions; do not state the tested general
knowledge or the entire cross-domain bridge as a supplied rule.

All four options must answer the same target in the declared answer form.
Use final outcomes rather than explanations. Put common information once in
the question. Put reasoning and error mechanisms in private metadata.

Respect the supplied length budget. Do not remove spaces, destroy code
indentation, omit necessary conditions, or discard a domain to meet it.
Do not mention difficulty, error categories, retrieval, or domain-coverage
requirements in the visible item.

Construct one correct option and one concrete wrong outcome for each retained
error type. In distractor_analysis.reason, explain the erroneous step and how
it produces that option. Do not expose the error label in the option text.

Preserve the existing JSON fields. Cite only actually used selected samples,
including at least one from each fusion domain. Record any substantive change
from the revised plan in plan_adjustment. Do not change the final target or
domain set silently. Return only the required English JSON object.
```

### 5.3 难度处理

保留 easy / medium / hard，但同一领域数量下使用相同长度预算。难度可通过知识应用条件、关系细节、边界情况、易混淆错误结果调节，不能主要靠增加背景和额外子问调节。

难度只是生成目标，新增 `difficulty_status="uncalibrated"` 或等价字段，不称为实测难度。三个难度候选明显重复时应标记，不能只改数字或标签便宣称难度不同。

## 6. 长度预算与统计口径

### 6.1 默认预算

| 总领域数（含源领域） | 题干软目标 | 题干硬上限 | 每选项硬上限 | 题干+四选项硬上限 |
|---|---:|---:|---:|---:|
| 2 | 30–55 | 75 | 18 | 130 |
| 3 | 40–70 | 95 | 20 | 160 |
| 4 | 50–85 | 115 | 22 | 190 |

单位为 `len(text.split())` 得到的英文词数，不是模型 token。选项可只有一个数值，不设置必须凑够的最小长度。软目标不是拒绝条件；硬上限才是质量检查条件。

统计只覆盖 question/options，不包含选项字母和后台元数据。分别记录 question_words、每个选项词数、options_words、total_visible_words、各字段字符数。

保留原 CLI 对领域数 2–7 的支持。对 5–7 可沿用如下线性外推，但必须在日志和预算元数据中标为 `uncalibrated_extension`，不能描述为已验证配置：

```text
extra = domain_count - 2
question_target_words = [30 + 10*extra, 55 + 15*extra]
question_max_words = 75 + 20*extra
option_max_words = 18 + 2*extra
total_visible_max_words = 130 + 30*extra
```

优先把预算放在 Python 常量或数据类中，并支持 `--length-budget-file` 覆盖。覆盖文件需验证类型、非负关系和字段完整性；不要到处硬编码。

### 6.2 代码与公式保护

同时设字符保护：默认每个字段的字符上限为该字段词数上限的 12 倍，总字符上限为总词数上限的 12 倍。这只是防止去空格绕过词数预算的宽松保护，不是已校准的 tokenizer 替代品。支持配置覆盖。

检查超长后必须返回具体问题并重写，绝不能 `text[:limit]` 截断题目、代码或检索证据。不要用删除空格、数学符号替换完整条件的方式规避预算。

原 `--max-tokens` 控制整个生成 JSON，保留原语义和默认值；不把它改成题干长度预算。原 `--max-input-chars` 继续保护发送给 API 的载荷，超长时报错，不能静默截断。

## 7. 局部结构校验与三类错误机制

### 7.1 结构校验

复用旧校验规则，但在第 4 步额外保证：

```text
options.keys() == {A, B, C, D}
answer in options
len(distractor_analysis) == 3
每种保留的错误类型恰好出现一次
每个错误选项恰好被注释一次
set(注释的 option) == {A, B, C, D} - {answer}
used_samples 的各领域引用均来自 selected_samples
```

原共享校验会压缩空白。不要把其压缩后的可见代码直接落盘：第 4 步局部保留原 question/options 的合法换行与缩进，仅去掉字符串首尾空白。其余字段可沿用共享规范化。不要修改共享函数导致上游行为改变。

如果直接调用共享校验会破坏某种可见字段的合法性，在第 4 步写局部兼容校验；不要以“通过了 JSON 校验”为由忽略代码格式。

### 7.2 错误类型仍然保留，但按构造机制解释

| 类型 | 应有机制 | 不应采用的写法 |
|---|---|---|
| missing_domain_knowledge | 缺少或错误使用某个参与领域的必要知识，产生具体错误结果 | 选项直接说“缺少某领域知识” |
| parallel_knowledge | 各局部知识或结果被识别，但一个必要结果未被传递或用于最终决策 | 选项直接说“没有整合、无法给出结果” |
| incorrect_domain_relation | 局部知识存在，但映射、方向、对象或组合关系错误 | 任意错误答案都套上“关系错误” |

`distractor_analysis.reason` 至少说明“哪一步错了 → 导致什么错误结果 → 为什么对应本选项”。不要只写类型名的同义句。

**重要边界：错误类型是构造者预设的机制标签，不是从一个简短数值答案唯一反推的模型认知诊断。** 不要求后续盲审仅看某个数字就唯一恢复 missing / parallel / relation 类型；否则会把题目逼回长解释选项。

因此，本次默认盲审验证答案和题目质量；错误类型做结构检查并保留可审计的机制说明。需要严格验证机制时，另做人工或单独的机制审查，允许审查者看到后台说明。不要把“生成器写了标签”记录成“独立验证已通过”。可用 `error_label_status="construction_intent"` 标明状态。

若生成时本身无法提出自然且可区分的三个错误机制，应该调整同源、同领域目标或拒绝，不用文字凑标签。

## 8. 语义审查：答案标签盲审，不是闭卷能力测试

### 8.1 默认行为与输入

默认对每个通过硬检查且已打乱的候选，额外调用一次审查模型。可通过 `--judge-model` 指定同一 API 端点的另一模型；默认复用生成模型配置。使用独立调用，不复用带有生成答案的对话历史。

审查输入包含：最终 question/options、参与领域、源样本及本题选中证据。不得包含拟定 answer、explanation、distractor_analysis、answer_plans、question_plan 或 compact_blueprint。

这是一种“隐藏答案标签、允许查证证据的质量审查”，不是闭卷模型能力测试，也不是独立专家验证。证据可用于核实通用领域知识，但不能补齐题面遗漏的实例特有输入。

### 8.2 审查内容与返回结构

审查实际题面，而不只看计划。检查：唯一正确性、单目标、自包含、证据支持、未直接赠送被测知识、选项同型、无明显表面捷径，以及每个领域的必要性。

建议结构如下；字段值中的枚举说明在实现时替换为实际单值：

```json
{
  "correct_options": ["C"],
  "solution_summary": "Brief verification of the final result.",
  "checks": {
    "single_target": "pass",
    "self_contained": "pass",
    "evidence_grounded": "pass",
    "no_knowledge_giveaway": "pass",
    "same_answer_form": "pass",
    "no_surface_shortcut": "pass"
  },
  "domain_necessity": {
    "actual_domain_name": {
      "necessary": true,
      "reason": "Which required inference uses this domain and what fails without it."
    }
  },
  "issues": []
}
```

`checks` 各项允许 pass / fail / uncertain；necessary 允许 true / false / null。correct_options 允许空列表或多个选项；不得为了符合 schema 强迫审查模型选一个。

由程序计算通过条件，不依赖模型一句 overall_pass：correct_options 必须恰好等于拟定答案的单元素集合，所有检查 pass，全部领域 necessary=true，且没有未解决的问题。uncertain 不算通过。

若审查答案与生成答案冲突，不要简单把 answer 改成审查答案；应进入定向重写或拒绝，同时保存冲突记录。审查模型也可能出错，日志用于后续复核。

审查提示词必须说明：“删除领域名后还能解”与“去掉该领域知识后还能解”不是同一个检查。题面中是否显式写出领域名字不是标准；检查它是否真正参与决定最终结果。不要声称一次 LLM 审查已经证明所有模型都无法走捷径。

### 8.3 AUDIT_PROMPT 核心文本

```text
Audit the actual visible multiple-choice item. No proposed answer key or
construction explanation is provided. Independently determine all correct
options, allowing none or several when the item is invalid or underdetermined.

The reference samples are private provenance. Use them to verify the tested
domain knowledge, not to supply instance-specific conditions missing from the
visible question. Judge self-containedness for a knowledgeable test taker who
cannot see these references.

Check that the item asks for one final target, not a bundled report; that all
options answer that target in the same form; and that the tested knowledge or
entire integration rule has not simply been given away.

For every participating domain, including the source domain, identify its
necessary contribution to the final result. Mentioning a domain, copying its
vocabulary, or selecting a sample from it does not establish necessity.
Flag avoidable answer cues, decorative domains, unsupported facts, ambiguity,
and missing conditions. Use uncertain rather than inventing certainty.

Return only the specified English JSON. Do not infer a unique cognitive error
category from a short wrong answer: such categories require separate review of
the construction mechanism.
```

## 9. 定向重写与失败行为

新增 `--max-repairs`，默认 1。含义是初稿失败后最多再生成一次，不包括初稿；不得写成无限 while 重试。

长度与语义失败应返回结构化 issues，包含失败字段、实际长度、上限、审查疑点及必须保留的知识约束。把原候选、具体反馈、选中证据、蓝图和预算发送给修复调用，不使用笼统的“请简洁一点”。

示例反馈：

```json
{
  "issues": [
    "question has 122 words; maximum is 95",
    "The options request three separate outputs instead of one final decision",
    "The geography contribution is decorative in the current item"
  ],
  "preserve": [
    "source sample core knowledge",
    "all selected participating domains",
    "one final target and one correct option",
    "supported facts and necessary conditions"
  ]
}
```

修复后必须重新执行所有结构、长度、引用、打乱和语义检查，不能因为上一次某项通过就复用旧的通过结论。保存每次尝试的结果。

质量失败拒绝该候选，继续同计划其他难度；筛选 infeasible 拒绝整个计划。API/JSON 失败沿用 JSONAPI 原有 retries；重试耗尽时按原行为明确报错并保留已完成输出，不得吞掉故障、伪装为普通质量拒绝。每种尝试和底层 API 重试分开计数。

原始输入不合法、路径冲突和 max-input-chars 超限应明确报错，不要把这些程序或数据错误混同于“模型认为不适合融合”。

## 10. 选项打乱与稳定标识

由程序而非生成模型决定最终选项位置。对每个合格格式的候选，在语义审查前进行一次可复现排列，同时更新 answer 和所有 distractor_analysis.option。

稳定标识建议：

```text
plan_key = upstream plan_id（若存在）
           否则 SHA256(规范化序列化的源样本、source_domain、
                       排序后的 fusion_domains、原始 question_plan、原始 answer_plans)

item_id = SHA256(generation_version, plan_key, difficulty)
shuffle_seed = SHA256(user_seed, item_id)
```

这里的规范化指 JSON 键序等确定性序列化，不是破坏源代码缩进的文本压缩。不要使用 Python 内置 hash()，不要把绝对路径作为内容身份。相同源样本和相同领域集合但不同原计划，必须可以得到不同 plan_key。

对完全相同的重复输入，明确报告重复并避免输出重复 item_id；不要碰撞后静默覆盖。

保留 old_label → new_label 的映射。必须测试实际答案文本、错误机制与标签一同移动，而不是只打乱 options。

自然语言解释尽量不引用“Option A/Choice B”等字母，而描述内容。禁止全局把字符 A/B/C/D 替换成新字母，这会破坏矩阵、变量和代码。发现无法安全映射的显式选项引用时，应重写而不是盲目替换。

每次修复得到的候选作为新的未排列对象，只排列一次；不在同一个已排列对象上反复累计打乱。审查输出中的字母必须与最终落盘的候选一致。

固定 seed 保证同一内容的排列可复现，不保证远程生成模型输出完全可复现，也不保证每个小分层恰好 25%。统计正确位置及各错误类型位置，不把小样本波动误判为程序错误。

## 11. 输出、日志与兼容性

### 11.1 正式输出

保留原输出字段：source_file、source_domain、model、sample、key_facts、fusion_domains、domain_count、question_plan、answer_plans、required_key_facts、retrieved_samples、retrieval、question、options、answer、explanation、distractor_analysis、used_samples、plan_adjustment、difficulty。

仅增加 item_id 和 construction 等后台字段。建议 construction 至少包含：

```json
{
  "version": "v4.1-concise",
  "plan_key": "stable-plan-key",
  "upstream_line": 1,
  "compact_blueprint": {},
  "original_plan": {},
  "length_budget": {},
  "length_stats": {},
  "scope_change": "none",
  "difficulty_status": "uncalibrated",
  "error_label_status": "construction_intent",
  "semantic_audit_status": "passed",
  "semantic_audit": {},
  "repair_count": 0,
  "option_permutation": {},
  "seed": 42
}
```

scope_change 使用明确枚举，如 none / presentation_only / target_narrowed。original_plan 保存筛选前的计划及必要知识需求，最终顶层计划仍按原逻辑保存筛选后版本。不要把原检索查询的元数据改写成“最终改写后的 key facts”，以免失去溯源。

按原代码保留检索候选及 retrieval 元数据；生成与 used_samples 仍只允许使用选中证据。必要时额外保存 selected_samples，不能把“所有检索候选”冒充“本题全部实际使用的证据”。

### 11.2 审计输出

提供 `--audit-output`。未指定时可使用同目录 `.audit.jsonl` sidecar 保持补丁兼容；新的批处理入口必须显式把审计文件写到单独的审计根目录，避免评测程序 glob 到它们。

为每个源计划记录筛选通过/拒绝；为每个难度的每次候选记录 accepted/rejected/repairing、原因、长度、审查结果及模型配置。正式输出只写最终接受题。

默认拒绝覆盖已有正式输出和审计文件，保留显式 `--overwrite`。在创建或截断任何一个文件前，先检查所有输入输出路径和冲突。输入、正式输出与审计路径不得指向同一文件。

不要求本次实现复杂断点续传；不要默认 append 导致重复。发生失败时清楚报告哪些输出已保留，重新运行时由用户选择新路径或显式覆盖。

统计区分输入计划数、可行计划数、初始候选数、修复候选数、接受题数和最终拒绝数。不能把每次修复都算作一个独立数据样本。

### 11.3 评测输入防泄漏

审查本地后续读取代码。模型输入应使用字段白名单，不能 `json.dumps(output_row)` 全量发送给被测模型。

最小可见表示：

```json
{
  "question": "...",
  "options": {"A": "...", "B": "...", "C": "...", "D": "..."}
}
```

若发现现有 evaluator 全量发送元数据，不在本次静默重写整个 evaluator；明确报告，并提供局部白名单修复或独立导出函数及测试。比较长度使用同一渲染口径。

## 12. CLI 和运行入口

保留原全部参数，新增：

```text
--max-repairs           int，默认 1
--seed                  int，默认 42
--judge-model           可选；默认与生成模型相同，同一 API 端点
--skip-semantic-audit    仅供格式调试，默认不跳过
--length-budget-file    可选 JSON 配置
--audit-output          可选审计文件路径
```

跳过语义审查时写 `semantic_audit_status="not_run"`，控制台警告；这些输出不能标记为正式质量合格。在统计脚本中与审查通过的题目分开报告。

`run_4_concise.sh` 可以读取原 run_config.sh 的领域、领域数和 API 配置，但输入保持旧 V4_ROOT 下的第 3 步，新输出由独立的 `V4_CONCISE_ROOT` 控制，审计由 `V4_CONCISE_AUDIT_ROOT` 控制。

建议默认布局：

```text
<PIPELINE_DIR>/outputs/3_retrieve_key_fact_matches/...             # 只读旧输入
<PIPELINE_DIR>/outputs_concise/4_generate_fusion_question/...      # 新正式输出
<PIPELINE_DIR>/outputs_concise_audit/4_generate_fusion_question/...# 新审计
```

不要仅把 V4_ROOT 改为 outputs_concise，那会连第 3 步输入路径一起改错。旧 run_4.sh 仍保持原行为。

在根目录的单组 smoke 命令应类似下面，按真实路径调整；新增参数实现后再运行：

```bash
python knowledge/pipielines_v4/4_generate_fusion_question.py \
  --input knowledge/pipielines_v4/outputs/3_retrieve_key_fact_matches/mathematics/test_domain_count_2.jsonl \
  --output knowledge/pipielines_v4/outputs_concise/4_generate_fusion_question/mathematics/test_domain_count_2.jsonl \
  --audit-output knowledge/pipielines_v4/outputs_concise_audit/4_generate_fusion_question/mathematics/test_domain_count_2.audit.jsonl \
  --domain-count 2 \
  --num 3 \
  --max-repairs 1 \
  --seed 42
```

沿用 API_BASE_URL / API_KEY / MODEL 环境变量，不在代码、文档或日志中写入真实 API key。首次试跑不使用 --overwrite。

无质量失败且三种难度均生成时，默认逻辑调用从原来的 1 次筛选 + 3 次生成，变成 1 次筛选 + 3 次生成 + 3 次审查。修复、API/JSON 重试另计。不要默认再加三次“重新规划”调用。

## 13. 离线统计与匹配对比

新增 audit_step4_concise.py，至少支持传入旧结果目录和新结果目录，输出 Markdown 或 JSON 统计报告，不依赖模型 API。

按 source_domain、domain_count、difficulty 分组，报告：题干和选项的均值/中位数/P95、总可见长度、预算超限率、正确答案位置、错误类型位置、接受率和拒绝原因。错误类型位置基于构造标签，不应宣称是观测到的模型错误原因。

读取新数据时排除审计文件；拒绝、修复与 accepted 未通过语义审查的 debug 记录分别统计。零接受时报告 0/N 和长度不可用，不伪造为长度 0 的合格题。

新旧匹配使用源样本、领域集合、原计划标识和 difficulty；旧记录没有原始 plan_key 时，回查共同的第 3 步输入或生成明确匹配清单。存在多重匹配时标记 ambiguous，不强行选一条。不得用“两个文件同一行”当作可靠配对，因为新流程会拒绝样本。

分别报告全体候选的覆盖情况和成功匹配样本的长度变化，说明拒绝带来的选择偏差。发生 target_narrowed 时称为“同源计划重构”，不称为严格等价的文字压缩。

## 14. 测试与验收

### 14.1 必须覆盖的离线测试

| 测试 | 预期 |
|---|---|
| 原第 3 步 JSONL 直接输入 | 无须迁移或重新检索 |
| feasible 蓝图缺少源领域/新增领域 | 拒绝 |
| infeasible 返回非空蓝图或选中证据 | 拒绝 |
| 选中、使用了错误领域或未供应样本 | 拒绝 |
| required_key_facts 仍为每域三个不同短语 | 旧约束保留 |
| 三个错误分析指向重复选项 | 拒绝 |
| 题干、单选项、总长度分别超限 | 得到字段级问题；不截断 |
| 短数字选项低于软目标 | 不因此拒绝 |
| 去空格的超长代码或公式 | 字符保护生效 |
| 合法多行代码 | 换行缩进原样保留 |
| 固定 seed 与相同 item_id | 同一选项映射 |
| 同源样本同领域但不同原计划 | 不同 plan_key |
| 打乱 | 正确答案文本、错误选项与分析一同映射 |
| 审查输入 | 不含 answer、解释、错误标签、计划、蓝图 |
| 审查返回零/多个答案、答案冲突、uncertain 或非必要领域 | 重写或拒绝，不自动改键 |
| 首稿失败、第二稿通过 | repair_count=1，仅输出最终稿 |
| 两稿都失败 | 不写正式题，写失败审计 |
| 某难度失败 | 继续其他难度，不强制三题齐全 |
| API 重试耗尽 | 报错，保留已完成输出与日志，不伪装质量拒绝 |
| 正式输出或审计文件已存在 | 无 overwrite 时预检失败，不提前截断另一文件 |
| skip-semantic-audit | 标记 not_run，不当成通过 |
| num 限制与计数 | 统计输入计划，不把修复计为新样本 |
| 旧第 0–3 步、共享函数和旧运行脚本 | 回归行为不变 |

使用 mock/FakeAPI 覆盖完整控制流，不能为了让测试通过默认关闭新审查或删除拒绝测试。用真实仓库已有测试入口运行，不要凭附件缺少外部依赖就伪造项目模块。

若本地环境缺依赖，说明哪些测试未运行、缺什么，不写“全部通过”。单元测试只能说明工程行为，不证明新题语义质量。

### 14.2 小样本验证

先完成离线测试。有已配置且授权的 API 时，只先做 3 个输入计划的 smoke；不默认全量生成。

正式对比试验可从七个现有源领域 × 三个领域数量中，每组固定 seed 抽取 3 个共同的第 3 步计划，共 63 个计划，最多 189 道候选。保存抽样清单，不通过“不断换计划直到成功”隐藏拒绝率。

人工复核新题是否只有一个最终目标、答案唯一、必要条件完整、各领域实际参与最终判断、错误机制说明合理。分别观察 2/3/4 领域的拒绝率及长度改善；不能只展示缩短最明显的例子。

长度降低是优化目标，不提前承诺某个比例。若缩短后大量领域不再必要，优先调整目标设计或适度放宽预算，不能把非必要领域审查关掉来提高通过率。

## 15. Codex 最终交付

完成后给出：修改文件清单及关键 diff、实际可运行命令、离线测试命令与结果、新 CLI 和 schema 文档、默认质量门控与拒绝行为、可复现统计脚本。

真实 API smoke 若确实运行，附少量新旧对应例子、接受/拒绝计数和长度统计；未运行则明确写“未进行真实模型生成，语义质量和接受率尚未验证”。不得用手工改写冒充新代码实测结果。

不要自动覆盖 v4 旧结果、重新跑第 0–3 步、启动全量付费任务或宣称论文级质量已验证。

最终原则：**后台保留完整证据和可审计机制；题面只保留必要条件和一个最终问题；减少显式任务展开，不削弱跨领域知识依赖。**

---

## 依据与范围说明

本规范依据用户上传的 `pipielines_v4.zip` 中的第 4 步源码、共享校验与运行脚本，以及前一轮生成的 `step4_concise_design.md`、`v4_sample_audit.md` 和修改补丁整理。源码与设计不一致时，先识别当前本地版本，再执行本规范中的明确修改要求。

参考源码位置（上传原版）：`4_generate_fusion_question.py:28–122` 筛选提示词，`:125–220` 生成提示词及例子，`:223–256` 筛选校验，`:259–379` 主流程，后续 main 为 CLI；`_pipeline_common.py` 中的 validate_required_key_facts / validate_generation 是必须保持兼容的共享约束。行号仅用于定位，不作为自动打补丁锚点。
