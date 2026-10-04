# 第 4 步：单目标简洁跨领域题（v5）

v5 直接读取现有第 3 步 JSONL，不要求迁移或重新检索。原筛选已允许调整旧计划，也已有简洁要求；本实现把这些要求落实为单目标蓝图、预算和质量门控。第 0–3 步算法、共享 JSONAPI / 校验行为、领域集合和既有结果保持不变；本目录运行入口变量、路径与文档统一使用 v5 命名。长度参数是本项目工程初值，不是 XDomainBench 官方参数或已验证结论。

## 流程与调用成本

一次筛选同时选择精确证据、调整旧计划及三短语知识需求、生成 `compact_blueprint`。随后分别生成 easy / medium / hard 候选，依次做原结构及引用校验、局部结构加强、词数/字符检查、程序化排列和独立答案标签盲审。审查不通过或硬检查失败，最多定向重写一次；重写候选重新执行全部检查。仍失败只写审计，继续其他难度，不强制凑三题。无失败时每计划为 1 筛选 + 3 生成 + 3 审查 = 7 次逻辑调用，重写及底层重试分开处理，不额外规划或检索。报告额外记录 logical_api_calls，审计记录 API retry 配置上限；共享 JSONAPI 不暴露成功调用内部实际重试次数，因此 transport_attempts 明确标 not_exposed_by_shared_JSONAPI，不伪造实测请求计数。

JSONAPI 仍处理 HTTP、无效 JSON、非对象响应以及筛选/审查 schema 失败的底层重试；生成候选对象的结构、长度和语义问题属于质量反馈，进入最多一次重写。API/JSON 重试耗尽会报错并保留此前正式输出与审计，不伪装成普通拒绝。`--max-input-chars` 超限及非法输入同样明确报错，绝不截断。

## 蓝图与题面

筛选新增 `compact_blueprint`：

- `target`：一个最终回答对象，默认最多 20 词。
- `answer_form`：number / decision / short_text / expression / code 中一个单值。
- `dependency_summary`：全部领域怎样共同决定结果，默认最多 70 词。
- `domain_roles`：恰好覆盖源领域及所有新增领域。各域含 `knowledge`、`role`、`removal_effect`，每字段默认最多 35 词。

每个新增领域仍恰好三个不同短语及 necessity，它们不是三个子问；证据必须来自该领域实际供应的原 prompt/completion。不可行时每域 selected_samples 为空，所有计划字段及蓝图为 null。一个目标可依赖多个推理步骤或多个共同约束，不能把独立计算和判断打包成报告。题干保留必要实例条件、单位、边界和局部接口，不能赠送被测通用知识/整条桥接规则。四个选项回答同一目标且同型，以最终结果呈现；解释和错误机制留在后台。合法换行、缩进仅去首尾空白，共享模块不改。code / expression 选项在局部比较时保留缩进与标识符大小写差异，避免共享空白压缩误拒合法结果。

三种错误类型保留：missing_domain_knowledge、parallel_knowledge、incorrect_domain_relation。每种恰好一次，三个错误选项各注释一次；reason 描述错误步骤及具体结果。短数值不能唯一反推出认知错误，标签状态为 `construction_intent`，不宣称独立机制审查通过。难度只是生成目标，标为 `uncalibrated`；同计划可见题干及无序选项完全重复会标记 `duplicate_difficulties`。只改数字的近重复仍需人工复核。

## 预算与 CLI

统计使用英文 `len(text.split())`，只统计 question/options，不计标签和后台记录。记录题干词数、每选项词数、选项合计、总可见词数，以及对应字符数；不等同于 tokenizer token。

| 总领域数 | 题干软目标 | 题干硬限 | 每选项硬限 | 总可见硬限 |
| --- | --- | --- | --- | --- |
| 2 | 30–55 | 75 | 18 | 130 |
| 3 | 40–70 | 95 | 20 | 160 |
| 4 | 50–85 | 115 | 22 | 190 |

软目标不作拒绝条件，无选项最小长度。每字段和总字符上限默认相应词限 × 12，防止去空格绕过。5–7 域按规范线性外推，在日志及预算标为 `uncalibrated_extension`；同领域数量的三个难度共享预算。超限反馈含具体字段、单位、actual、limit，绝不通过截断、删除必要条件或领域降低长度。

保留所有旧参数与默认值：`--input`、`--output`、`--domain-count`（可选 2–7 校验）、`--num`、API 三参数、`--timeout`（180）、`--retries`（2）、`--max-tokens`（4096，整个 JSON 的 token 上限）、`--max-input-chars`（160000，整个 API 载荷字符上限）、`--overwrite`。`--num` 限制输入计划数，修复不计新计划。

| 新参数 | 默认及含义 |
| --- | --- |
| `--max-repairs` | 1，允许 0 或 1，初稿之外的重写次数 |
| `--seed` | 42，用于稳定选项排列 |
| `--judge-model` | 不指定则复用生成模型，同端点独立调用 |
| `--skip-semantic-audit` | 默认关闭；仅格式调试，警告并标 not_run，不能算质量通过 |
| `--length-budget-file` | 可选 JSON 预算覆盖及蓝图长度上限 |
| `--audit-output` | 不指定为 output 同目录 `.audit.jsonl` sidecar |

预算文件支持只覆盖指定领域数，但每个覆盖预算必须完整：

```json
{
  "budgets": {
    "2": {
      "question_target_words": [30, 55],
      "question_max_words": 75,
      "option_max_words": 18,
      "total_visible_max_words": 130,
      "question_max_chars": 900,
      "option_max_chars": 216,
      "total_visible_max_chars": 1560
    }
  },
  "blueprint_limits": {"target": 20, "dependency_summary": 70, "domain_role": 35}
}
```

检查整数类型（拒绝 bool）、非负性、软目标顺序、总预算与单字段关系和完整字段；蓝图上限必须为正整数。未覆盖的领域数继续使用默认值。

## 盲审与失败

盲审只收到最终 question/options、参与领域、源样本和所选证据，不收到 answer、解释、干扰项、计划和蓝图；它是允许查证参考证据的答案标签盲审，不是闭卷能力测试。证据只能核实知识，不能补齐题面遗漏的实例条件。

程序计算通过条件：correct_options 恰好为拟定答案，六项检查全部 pass，所有领域 necessary=true，issues 为空。检查包括单目标、自包含、证据支持、无知识赠送、选项同型、无表面捷径。零/多答案、答案冲突、uncertain、装饰性领域均失败。程序不会直接把答案改成 judge 结果。一次 LLM 审查不是独立专家验证，也不能证明所有模型均无捷径。

定向重写收到原候选、具体问题、完整构造约束、证据、蓝图及预算。语义反馈另保存实际已排列候选与映射，避免审查字母和原稿字母混淆。每次尝试均记日志；接受率分母是初始候选，不把修复当成新样本。

## 兼容字段和稳定标识

正式行保留 source_file、source_domain、model、sample、key_facts、fusion_domains、domain_count、question_plan、answer_plans、required_key_facts、retrieved_samples、retrieval、question、options、answer、explanation、distractor_analysis、used_samples、plan_adjustment、difficulty。顶层计划保存筛选后版本；retrieved_samples 保留全部原检索问答，retrieval 保持原元数据。仅 selected_samples 可用于构造/used_samples，不能把所有候选称为实际证据。

新增 `item_id` 和 `construction`。construction 含 version=`v5-concise-1`、plan_key、upstream_line、compact_blueprint、original_plan（筛选前 question_plan / answer_plans / required_key_facts）、selected_samples、length_budget、length_stats、scope_change、difficulty_status、error_label_status、semantic_audit_status、semantic_audit、repair_count、option_permutation、seed、生成/审查模型、duplicate_difficulties。原计划有变化时保守标为 `target_narrowed`，比较时称同源计划重构，不宣称严格等价文字压缩；无变化为 none。

plan_key 优先使用非空 upstream plan_id，否则 SHA256 规范 JSON 的源问答、源域、排序领域集合和原问题/答案计划；不依赖路径或 Python hash()，不压缩代码。item_id 为 SHA256(version, plan_key, difficulty)，排列种子为 SHA256(seed, item_id)。同步移动实际选项文本、answer 和所有干扰项标签，保存 old→new 映射；不全局替换变量 A/B/C/D。检测到明确自由文本选项字母引用会要求重写。完全相同输入报告 duplicate 并跳过，显式 plan_id 对不同构造输入的冲突会报错。每次重写稿重新作为未排列对象，只排列一次。

固定 seed 保证排列可复现，不保证远程生成或小分组答案位置恰好均衡。

## 输出隔离与运行

默认拒绝覆盖正式文件和审计文件；创建/截断任何文件前检查全部路径、别名和已有文件。输入、正式输出和审计不得相同。显式 `--overwrite` 才允许覆盖；失败后已完成内容保留，不自动 append 或续传。批处理先预检所有组。

新入口 `run_4_concise.sh` 只运行第 4 步，读取本目录 run_config 的领域、数量、API 和 NUM/STEP_4_ARGS。第 3 步输入根为 V5_ROOT，新输出根 V5_CONCISE_ROOT，审计根 V5_CONCISE_AUDIT_ROOT，默认分别是 outputs、outputs_concise、outputs_concise_audit。批入口要求三根不同，显式把审计放独立目录，避免评测 glob 读入。

当前 v5 的 outputs 已有第 0–3 步结果，第 3 步共 21 个输入文件、2100 个计划；默认直接读取本目录 outputs。下面命令使用已有第 3 步 JSONL，无须重新检索。运行时由环境提供已授权 API 配置。

在仓库根目录，首次仅处理 3 个输入计划（最多 9 道初始候选）：

```bash
# API_BASE_URL、API_KEY、MODEL 由已授权环境提供，不在命令/日志写真实 key。
STEP3_INPUT=knowledge/pipielines_v5/outputs/3_retrieve_key_fact_matches/mathematics/test_domain_count_2.jsonl
PYTHONDONTWRITEBYTECODE=1 /mnt/data1/wangyatong/anaconda3/envs/crossx/bin/python \
  knowledge/pipielines_v5/4_generate_fusion_question.py \
  --input "$STEP3_INPUT" \
  --output knowledge/pipielines_v5/outputs_concise/4_generate_fusion_question/mathematics/smoke3.jsonl \
  --audit-output knowledge/pipielines_v5/outputs_concise_audit/4_generate_fusion_question/mathematics/smoke3.audit.jsonl \
  --domain-count 2 --num 3 --max-repairs 1 --seed 42
```

后续明确需要批量时才运行；`NUM=3` 是每组 3 计划，不是本次授权的总计 3 计划 smoke：

```bash
V5_ROOT="$PWD/knowledge/pipielines_v5/outputs" \
V5_CONCISE_ROOT="$PWD/knowledge/pipielines_v5/outputs_concise" \
V5_CONCISE_AUDIT_ROOT="$PWD/knowledge/pipielines_v5/outputs_concise_audit" \
NUM=3 bash knowledge/pipielines_v5/run_4_concise.sh
```

## 离线统计、匹配和评测输入

`audit_step4_concise.py` 不发模型请求，以相同 question/options 统计口径对比新旧目录。按源域、总领域数、难度和审查状态分组，报告题干/选项/总可见词数及字符的均值、中位数、线性插值 P95、超限率、答案位置和构造错误类型位置。审计另报输入/可行/重复计划、初始/修复候选、接受/最终拒绝、调试输出、故障、拒绝/重写原因，以及候选长度。零接受显示 0/N，长度不可用为 null，不将拒绝稿当合格零长度题。未提供 audit-root 时接受率不可用。

匹配包含源问答、领域集合、原计划身份和 difficulty；不会用文件同行配对。旧行没有原身份时可回查共同 --upstream-root：精确原计划匹配或同源领域唯一原计划才能关联；多计划无法定位标 ambiguous。也支持 --match-manifest JSON：`绝对旧文件路径:物理行号 -> 原始plan_key`。没有回查时只尝试原计划内容相同的配对，无法确认则 unmatched。新旧同身份有多条均标 ambiguous。报告全体覆盖、成功匹配和长度变化，明确拒绝带来的选择偏差。

```bash
python knowledge/pipielines_v5/audit_step4_concise.py \
  --old-root /absolute/path/to/old/4_generate_fusion_question \
  --new-root knowledge/pipielines_v5/outputs_concise/4_generate_fusion_question \
  --audit-root knowledge/pipielines_v5/outputs_concise_audit/4_generate_fusion_question \
  --upstream-root /absolute/path/to/common/3_retrieve_key_fact_matches \
  --output /tmp/step4_concise_report.json
```

扫描结果排除 audit 文件，报告输出拒绝覆盖已有文件。后台审计不是被测模型输入。仓库没有发现读取本步骤完整行并全量发送的融合题 evaluator；相邻 benchmark 的 medical_eval / evaluate_domain_lora_train 使用显式 prompt。新增 `_concise_fusion.visible_item(row)` 只返回 question/options，有离线防泄漏测试。接入评测时只序列化此白名单并附统一答题指令，answer 和所有 construction 仅用于离线评分/溯源。

## 离线验证与边界

```bash
PYTHONDONTWRITEBYTECODE=1 /mnt/data1/wangyatong/anaconda3/envs/crossx/bin/python \
  -m unittest discover -s knowledge/pipielines_v5/tests -v
bash -n knowledge/pipielines_v5/run_4_concise.sh
```

测试包含蓝图/引用/schema、三短语约束、干扰项覆盖、各项长度和字符防绕过、多行代码、稳定 ID 和排列同步、防泄漏审查、定向修复/拒绝、各难度继续、API 重试耗尽、预检不截断、调试状态、num/重复计数、统计匹配，以及原第 0–3 步和 shell 回归。Mock 题目和 judge 只验证工程控制流，不验证生成质量。

2026-10-04 实际验证：v5 测试 44/44 通过；同一 Python 环境运行 `knowledge/pipelines/tests` 共享流程测试 38/38 通过，原副本回归 17/17 通过。`bash -n`、统计 CLI 独立启动和 `git diff --check` 通过。该次实施未修改第 0–3 步、共享校验器或旧结果；随后本目录入口变量与文档路径统一迁移为 V5_* / v5_*，第 0–3 步算法不变。

未进行真实模型生成，语义质量、真实接受率、2/3/4 域长度改善、近重复难度、5–7 域预算和错误机制的人工复核尚未验证。不得以离线测试通过宣称这些结论成立。
