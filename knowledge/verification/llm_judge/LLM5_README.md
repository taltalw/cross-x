# LLM5 英文 Prompt 与评审流程

已实现：两位隔离初审（各两阶段）、固定规则复核与分层抽查、第三位先独立再看匿名初审、五维统计、人工待核验路由。Python 3.10+，仅标准库。

最新更新：[必要性规则修复与同样本复测报告](LLM5_必要性规则修复与单样本复测_20261005.md)。v2已完成同题重跑，第三位必要性建议1分，样本进入人工核验；原始输出保留。

模型看到的 system、rubric、阶段任务和修正提示均为英文，默认要求英文评审输出；使用说明为中文。

## 一键评估 pipelines v5 / v6

以下命令在 `cross-x` 项目根目录运行（Python 3.10+，仅标准库）：

```bash
J1_API_BASE_URL='Claude的API地址' \
J1_API_KEY='Claude的API密钥' \
J1_MODEL='claude-opus-5' \
J2_API_BASE_URL='Gemini的API地址' \
J2_API_KEY='Gemini的API密钥' \
J2_MODEL='gemini-3.1-pro' \
J3_API_BASE_URL='DeepSeek的API地址' \
J3_API_KEY='DeepSeek的API密钥' \
J3_MODEL='deepseek-v4-pro' \
bash knowledge/verification/llm_judge/LLM5_run_v5_v6.sh
```

在终端分别填写三个角色的服务地址、密钥和模型名。执行模式要求上面九个变量全部填写，地址和密钥可以相同，也可以各不相同。脚本不内置服务地址，也不将密钥写入配置或评审输出。各角色的 `*_API_BASE_URL` 可以是带 `/v1` 的 Base URL，也可以是完整的 `/chat/completions` 地址；脚本仅补上 `/chat/completions`，不自动添加 `/v1`。各接口需支持现有客户端的 OpenAI 兼容聊天与 JSON 输出参数。模型名按终端的 `J1_MODEL` / `J2_MODEL` / `J3_MODEL` 原样发送。

推理强度默认按模型名选择：模型名包含 `gpt` 时发送 `reasoning_effort="xhigh"`，其他模型发送 `reasoning_effort="max"`，包括初审、独立复核、整合及重试。声明为 deepseek 家族时还默认发送 `thinking={"type":"enabled"}`。Gemini 的兼容接口将 `reasoning_effort` 映射到 thinking level；DeepSeek 使用 thinking 开关及 reasoning effort，参考 [Gemini 文档](https://ai.google.dev/gemini-api/docs/openai)、[DeepSeek 文档](https://api-docs.deepseek.com/guides/thinking_mode/)。Claude 的实际强度取决于所用网关是否映射该参数；[Claude 官方兼容层](https://platform.claude.com/docs/en/cli-sdks-libraries/libraries/openai-sdk)会忽略 `reasoning_effort`，不能仅凭请求参数宣称 max 已生效。

各角色可通过终端变量覆盖，例如 `J1_REASONING_EFFORT=xhigh`、`J2_REASONING_EFFORT=max`、`J3_REASONING_EFFORT=max`；不填写时按上述模型名规则自动选择。`J3_THINKING=enabled` 开启、`disabled` 关闭，支持该格式的网关可用 `J1_THINKING=adaptive`。接口不支持某参数时，可显式设置对应的 `*_REASONING_EFFORT=omit` 或 `*_THINKING=omit` 不发送该字段；脚本不会因 HTTP 报错自动降级。高级 JSON 配置中用 `reasoning_effort: null` / `thinking: null` 达到相同效果。配置和调用记录保留实际请求参数，不保存内部推理正文。

| 角色 | 终端示例模型 | 工作 |
|---|---|---|
| J1 | `claude-opus-5` | 每题两阶段独立初审 |
| J2 | `gemini-3.1-pro` | 每题两阶段独立初审 |
| J3 | `deepseek-v4-pro` | 分歧、异常及一致通过样本的 10% 分层抽查；先独立两阶段，再匿名复核 |

默认顺序评估 `pipielines_v5/outputs` 和 `pipielines_v6/outputs` 下的 `4_generate_fusion_question/*/test_domain_count_[234].jsonl`，读取全部非空物理行；不读取 `.audit.jsonl` 或前序阶段结果。两套输入先全部校验，再发送请求。当前文件共有 v5 2310 题、v6 2223 题，全量至少需要 18132 个初审阶段，另有复核和失败重试。建议先用小批量检查网关兼容性：

```bash
J1_API_BASE_URL='Claude的API地址' \
J1_API_KEY='Claude的API密钥' \
J1_MODEL='claude-opus-5' \
J2_API_BASE_URL='Gemini的API地址' \
J2_API_KEY='Gemini的API密钥' \
J2_MODEL='gemini-3.1-pro' \
J3_API_BASE_URL='DeepSeek的API地址' \
J3_API_KEY='DeepSeek的API密钥' \
J3_MODEL='deepseek-v4-pro' \
bash knowledge/verification/llm_judge/LLM5_run_v5_v6.sh --limit 1
```

`--limit 1` 为每个版本各取第一题，仍使用三模型正式协议，J3 按复核规则选样。无需服务地址或密钥的全量离线预览（未指定的模型名仅在预览中使用上表示例）：

```bash
bash knowledge/verification/llm_judge/LLM5_run_v5_v6.sh --dry-run
```

常用参数：`--versions v5` 只评估 v5；`--domains computer_science mathematics` 筛选源领域；`--domain-counts 3 4` 筛选融合领域数；`--limit N` 限制**每个版本总题数**；`--output-dir 新目录` 指定输出；`--v5-root` / `--v6-root` 指定各版本的 outputs 目录（也可设置 `V5_ROOT` / `V6_ROOT`）；`--atomic-root` 指定原子资料目录。解释器可通过 `LLM5_PYTHON` 或 `PYTHON_BIN` 指定。

每次创建新的 `LLM5_outputs/LLM5_v5_v6_时间戳/`，包括不含密钥的 `LLM5_config.json`、总运行清单 `LLM5_batch_manifest.json`，以及分别独立的 `v5/`、`v6/` 运行目录。执行时，各版本的报告位于 `v5/LLM5_statistics/LLM5_report.md` 和 `v6/LLM5_statistics/LLM5_report.md`；详细调用产物持续写入各自 `LLM5_calls/`。离线预览只输出规范样本和 Prompt，不生成评分报告。

脚本拒绝覆盖非空输出目录；任一版本执行不完整时返回非零退出码并停止后续版本。当前不支持断点续跑，重新执行会创建新批次。J1/J2/J3 默认声明家族为 anthropic/google/deepseek；若更换模型家族，可分别设置 `J1_FAMILY` / `J2_FAMILY` / `J3_FAMILY`，正式模式要求三个不同家族。需要额外的受支持参数时，可使用 `--config 本地配置.json` 提供现有三模型配置结构，此时配置文件优先；密钥仍只通过配置中的 `key_env` 环境变量读取。

### 在另一台服务器运行

脚本内部通过脚本自身的位置定位文件，没有写死本机的 `/mnt/data1/wangyatong` 或其他用户目录。迁移时保留下列结构，项目可以放在新服务器上的任意位置：

```text
cross-x/
└── knowledge/
    ├── verification/
    │   └── llm_judge/
    │       ├── LLM5_run_v5_v6.sh
    │       ├── LLM5_*.py
    │       └── LLM5_prompts/
    ├── pipielines_v5/outputs/4_generate_fusion_question/
    ├── pipielines_v6/outputs/4_generate_fusion_question/
    └── atomic/
```

至少复制 `llm_judge` 的全部 Python 文件、启动脚本和 `LLM5_prompts`，以及两个版本阶段4的题目结果。`atomic` 用于本地原子来源精确匹配，建议一起复制；缺失时使用题目内嵌材料并标记来源未定位。旧 `LLM5_outputs`、pipeline 前序阶段输出及生成环境无需复制。

新服务器需要 Bash、Python 3.10+，执行用户对输出位置有写权限，并能访问所配置的三个 OpenAI 兼容 API。先在新服务器的 `cross-x` 根目录执行：

```bash
bash knowledge/verification/llm_judge/LLM5_run_v5_v6.sh --dry-run --limit 1
```

预览成功后，使用上方的九个环境变量命令进行真实试跑。若不保留默认目录结构，可以在命令末尾加 `--v5-root 新位置/v5/outputs --v6-root 新位置/v6/outputs --atomic-root 新位置/atomic`；默认输出写到当前脚本所在目录的 `LLM5_outputs`，也可用 `--output-dir 新输出目录` 指定。运行清单中的绝对路径记录的是执行时服务器上的实际来源位置，不是写死的程序配置。

设计依据：[五维评审与 Prompt 设计](LLM5_五维评审与Prompt设计_20261005.md)。本轮 DeepSeek 单题真实测试已完成，结果见 [单样本测试报告](LLM5_单样本API测试报告_20261005.md)。该次运行的最终统计位于 `LLM5_outputs/LLM5_deepseek_smoke1/LLM5_statistics_verified`，已离线修正流程测试与合成数据的元数据混淆，未改变模型回答或追加API调用。

## 代码与英文 Prompt

| 文件 | 职责 |
|---|---|
| `LLM5_data.py` | 单题选择、字段白名单、匿名ID、atomic来源精确匹配 |
| `LLM5_prompts.py` | 每阶段新会话，JSON安全序列化，Prompt版本与摘要 |
| `LLM5_schema.py` | 结构、分数、引用、指针和显式矛盾校验 |
| `LLM5_api.py` | HTTP客户端、模型发现、失败分类、凭据保护 |
| `LLM5_run.py` | 初审→选样→复核→统计的编排入口 |
| `LLM5_aggregate.py` | 分母明确的统计、触发/抽查与人工路由 |
| `LLM5_run_example.sh` | prepare/smoke/test脚本 |
| `LLM5_config.example.json` | 三模型配置结构示例，使用前替换占位符 |

英文文本可以直接查看：

- [共同 System](LLM5_prompts/LLM5_system.txt)
- [完整五维量表](LLM5_prompts/LLM5_rubric.md)
- [阶段1：盲审题目结构](LLM5_prompts/LLM5_stage1.txt)
- [阶段2：证据核验与打分](LLM5_prompts/LLM5_stage2.txt)
- [第三位：匿名复核](LLM5_prompts/LLM5_review.txt)

代码不读取旧CDNS结果，不把生成模型的必要性说明注入评审。第一阶段只提供匿名ID、question、options和空visible_inputs；第二阶段增加声明领域、参考答案/解释、明确的单选判分契约和sample/used_samples材料。这里的解释是待核验主张，不能作为自身正确性的独立证据。

## 默认测试样本与来源

默认输入：`../../pipielines_v4/outputs/4_generate_fusion_question/computer_science/test_domain_count_3.jsonl`，物理第1行，easy三域题。

涉及computer_science、mathematics、financial：IPv4可变首部、传输时间换算、固定费用加时间收费。源域材料来自sample，新增域来自used_samples，不把全部检索候选误称为生成依据。

atomic来源匹配使用完整prompt/completion的摘要；能定位时记录文件、物理行号和SHA256，找不到时保留嵌入材料并标记`embedded_only_atomic_unresolved`。本地原子样本可追溯不等于原始教科书或权威资料已核验。来源路径、生成器别名只存内部metadata，不进入模型Prompt。

本实现默认评审正式question+options任务。若未来任务正式发布时还提供额外材料，需要单独制定并实现新的可见输入协议，不能自动把used_samples当成答题者本来能看见的输入。

## 仅准备输入（不调用API）

```bash
# 从 cross-x 项目根目录进入评审目录。
cd knowledge/verification/llm_judge
bash "LLM5_run_example.sh" prepare --output-dir "LLM5_outputs/LLM5_preview_again"
```

保存规范样本、运行清单、第一阶段实际消息预览。dry-run不读取密钥、不请求模型列表、不发送模型调用。所有命令都拒绝覆盖已有非空输出目录。

选择其他单个样本使用 `--input "路径.jsonl" --line 物理行号`。本次授权测试仅使用默认这一题，未扩展其他样本。

## DeepSeek 单题流程测试（会调用API）

交互式隐藏输入密钥：

```bash
python3 -X utf8 "LLM5_run.py" \
  --smoke-one --execute --prompt-key \
  --output-dir "LLM5_outputs/LLM5_smoke_new"
```

也可以在运行环境中设置 `DEEPSEEK_API_KEY` 后执行脚本，不要把密钥写入配置、脚本或命令历史：

```bash
bash "LLM5_run_example.sh" smoke --output-dir "LLM5_outputs/LLM5_smoke_new"
```

`--smoke-one` 强制恰好一个样本，并强制走第三位复核以测试完整链路。三个角色使用同一个DeepSeek模型，但每次会话隔离；这只是流程测试，`independent_validation=false`，不能报告为三个独立模型的质量证据。即使全部打高分，也不能据此宣布样本已被人工核验或跨家族验证。

默认通过DeepSeek官方 `/models` 发现当前可用模型，优先Flash，再回退兼容列表中的其他模型。请求模型与服务返回model都记录。通常共1次模型列表请求、7个评审阶段：J1两次、J2两次、J3独立两次加整合一次；错误时每阶段最多额外重试2次，因此API请求数可能大于7。

官方接口参考：[首次调用](https://api-docs.deepseek.com/)、[Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)。当前默认使用JSON响应格式、temperature=0、max_tokens=7000、thinking=enabled（DeepSeek）、GPT 模型 `reasoning_effort=xhigh`、其他模型 `reasoning_effort=max`、非流式；旧单样本测试使用的 thinking=disabled 以当时的运行清单为准。统计保留返回usage，未自行估算账单费用。

密钥只进入运行进程和官方请求的Authorization头，不存储到输出。拒绝携带凭据的URL及HTTP重定向；HTTP错误只记录类别和状态码，不记录服务错误正文；响应中的密钥样式文本会脱敏。不把API返回的内部reasoning_content写入报告。

401/402/403等终止性问题会停止后续调用，429/暂时性服务错误可有限重试。输出JSON、引文或分数字段不合法时定向重试；修正提示不会指定应给几分，也不会由程序擅自改分。

## 正式三模型配置

将配置示例中的endpoint/model/family/key_env替换为实际值。接口需支持聊天messages、JSON对象输出和所配置的解码参数；不同服务的兼容性尚未通过本次DeepSeek测试证明。

```bash
python3 -X utf8 "LLM5_run.py" \
  --config "LLM5_config.local.json" \
  --input "../../pipielines_v4/outputs/4_generate_fusion_question/computer_science/test_domain_count_3.jsonl" \
  --line 1 --execute --output-dir "LLM5_outputs/LLM5_three_family"
```

不指定 `--execute` 则只做输入准备。正式配置要求三个不同声明家族、不同endpoint/model身份，模型名不能为auto。家族信息由操作者核实；代码无法从任意API别名确认真实权重血缘，manifest标记`declared_not_verified`。当前生成器家族未知，因此不能宣称已确认与生成器不同家族。

`--samples-file`可接收已经准备、含content_sha256的规范JSONL，用于将来正式批次；本轮没有批量API运行。样本输入摘要不一致即拒绝执行。任何Prompt/配置/量表变更都用新的输出目录，不覆盖或混拼旧运行。

## 输出与统计

当前英文Prompt版本为 `LLM5-en-v2-20261005`。阶段2和第三位整合均必须提供 `necessity_audit`：

- `verified_shortcut`：提供可核查解法、所省略领域、由该解法得到的答案及正式可见输入指针，必要性必须为整数0–2；省略领域标记为冗余。
- `unresolved`：关键必要性疑点未能核验，且没有已确认的有效反例，必要性必须为 `unjudgeable/null`，可用原因 `unresolved_necessity`，进入复核；复核仍未决则人工处理。
- `not_found`：当前检查未发现有效捷径或遗留关键疑点，不等于证明必要性，也不自动获得合格分。

已有确定反例优先于其他未决疑点，不将确定失败改成未知。必要性疑似flag或域贡献uncertain不能与not_found并存；漏填flag也会根据审计状态触发路由。程序只校验结构及判断一致性，不能自动证明模型所写解法的语义正确性。违反规则的响应原样保存并定向重试，不直接改分；其他四维保持独立。

```text
LLM5_outputs/某次运行/
├── LLM5_samples.jsonl             # 规范输入与内部追溯
├── LLM5_run_manifest.json         # 模式/实际配置/Prompt与代码摘要/调用数
├── LLM5_records.jsonl             # 每样本每角色每阶段唯一的最终记录
├── LLM5_calls/                    # 每次尝试的实际英文请求与返回、错误信息
├── LLM5_review_selection.json     # 固定规则触发/抽查名单
├── LLM5_anonymous_mapping.json    # P/Q映射，只供审计
└── LLM5_statistics/
    ├── LLM5_summary.json
    ├── LLM5_dimensions.csv
    ├── LLM5_disagreements.csv
    ├── LLM5_joint.csv
    ├── LLM5_groups.csv
    ├── LLM5_J3.csv
    ├── LLM5_routes.csv
    ├── LLM5_audit_strata.csv
    └── LLM5_report.md
```

每维`scored`对应0–4整数，`unjudgeable`对应null。服务/格式失败保持执行失败，不伪造为U，也不当成0分。均分排除U；主达标率将U保留在共同完成双评审的分母；五维联合通过不允许任何U或<3。SD使用样本标准差，数值样本不足2时为null。

固定触发：同维差≥2、跨3分门槛分歧、U、关键错误/捷径/域冗余/来源矛盾。漏填flags也会从明确的答案错误、歧义或域冗余结构化字段派生触发。无触发且一致通过按源域×k×难度10%分层抽查，非空层向上取整，固定种子且与输入顺序无关。

J3先独立两阶段，然后看匿名P/Q。复核集合按固定种子排序、交替P/Q映射，控制意见顺序。J3数据按触发/抽查/强制复核分别报告，不与J1/J2主表混平均。

关键错误、尚未解决问题、复核后U、联合通过结论改变等会进入`pending_human`。查看`LLM5_routes.csv`及其中human_review_reasons；代码不会自动伪造人工裁决。实际人工核查及裁决回写是后续人工流程，本轮未执行。

可在不调用API的情况下重新汇总：

```bash
python3 -X utf8 "LLM5_aggregate.py" \
  --run-dir "LLM5_outputs/LLM5_deepseek_smoke1" \
  --output-dir "LLM5_outputs/LLM5_reaggregate"
```

主汇总报告不计算五维加权总分；数值统计与机器路由分开。当前单模型烟测的任何通过率都只是流程产物，不是全量数据集质量估计。

## 离线验证

```bash
bash "LLM5_run_example.sh" test
```

52项测试覆盖：原31项英文Prompt、阶段数据隔离、2/3/4域、来源匹配与伪引文、严格分数/未知状态、统计分母与触发、7阶段模拟执行、定向重试、鉴权停止、dry-run零调用、输出保护、同模型假家族拒绝、U+2028及API凭据保护；另21项覆盖必要性0–2/U边界、合法证据、漏flag路由及第三位复核约束。

未验证范围：真实的三种模型家族一致性、其他服务接口兼容性、多样本质量水平和人工裁决效果。需要正式独立评审时应先完成模型配置与人工量表校准。
