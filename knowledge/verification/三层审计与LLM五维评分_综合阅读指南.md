# 三层审计与 LLM 五维评分：综合阅读及运行指南

版本：2026-10-05。本文以当前代码和已保存结果为准，串联 **Process Auditing → LLM 五维评审 → Human Verification**。这里“三层”是三层质量检查；第一层内部包含DDE、KNC/KRC、CDNS，不是三个互斥打分模型。

## 先回答：只发 verification 是否足够？

**交流指标设计、阅读实现和英文Prompt、查看现有报告与图表、运行单元测试和部分历史结果重统计：足够。** 当前包已包含代码、测试、设计文档、所需附图和历史输出。

**在另一台机器上从原始样本重新评测完整数据集：还不够。** 完整`pipielines_v4/outputs`与`atomic`原语料不在本包；API密钥、模型权重和Python环境也不在包内。历史报告可能内嵌少量样本和来源材料，但不等于完整数据集。第三层的真实人工裁决尚未实施。

审计目录名统一为`process_auditing`：

```text
verification/
├── README.md
├── 三层审计与LLM五维评分_综合阅读指南.md
├── PACKAGE_MANIFEST.json
├── PACKAGE_VALIDATION.json
├── process_auditing/
│   ├── README.md
│   ├── DDE/       # 代码、脚本、说明、DDE_tests、DDE_outputs
│   ├── KNC/       # 保存分数的保守覆盖代理指标
│   ├── KRC/       # 仅有分数支持集的条件覆盖代理指标
│   ├── CDNS/      # Prompt内材料遮蔽
│   └── design_docs/  # 当前/历史设计说明和论文附图
└── llm_judge/
    ├── LLM5_*.py、LLM5_run_example.sh、LLM5_config.example.json
    ├── LLM5_prompts/  # 英文system、五维量表、两个阶段与复核模板
    ├── LLM5_tests/
    └── LLM5_outputs/  # 两轮单样本真实流程测试及离线准备记录
```

推荐顺序：先读本文；再读各指标README和[设计文档索引](process_auditing/design_docs/README.md)；最后检查真实记录或运行命令。历史待确认方案不代表当前实现口径。

## 三层各自回答什么

| 层次 | 主要问题 | 产出 | 不能替代什么 |
|---|---|---|---|
| Process Auditing | 选域是否多样、检索是否覆盖需求、移除材料是否影响作答 | DDE、KNC/KRC、CDNS/DC/IG及可用率、分母诊断 | 分数不直接证明每题内容正确 |
| LLM五维评审 | 最终题是否必要跨域、真正融合、正确可判分、有依据且表达自然 | 五维0–4/U、证据、争议、复核与人工路由 | 机器共识不等于人工验收 |
| Human Verification | 关键争议和机器共同盲点是否成立 | 人工逐维结论、证据、修订/保留/舍弃决定 | 尚未执行的人工核验不能写成已通过 |

三部分证据分别保留。两位LLM初审不看彼此结果，也不看CDNS mask结果，避免把“某模型遮蔽后答错”当作题目必然跨域的答案。不要把所有指标合成一个不透明总分。

## 运行环境和路径约定

Python 3.10+。指标计算、测试及HTTP客户端只依赖标准库；可选绘图需matplotlib/numpy。无需为了离线计算再加载Embedding模型。

下文命令均从**解压后的verification目录**执行。将`/path/to/verification`替换为自己的路径：

```bash
cd "/path/to/verification"
```

完整重算时再设置外部数据目录，不能把示例路径当作已随包提供：

```bash
PIPELINE_OUTPUTS="/path/to/pipielines_v4/outputs"
ATOMIC_ROOT="/path/to/atomic"
```

原仓库中的实际值分别为`knowledge/pipielines_v4/outputs`与`knowledge/atomic`。历史JSON里的原工作区绝对路径和代码摘要保留原值；复制到其他机器后，这些字符串只是历史溯源信息。需要严格来源核验时应恢复原数据或重新生成当前运行清单，不能批量改旧哈希冒充原实验。

## 第一层：Process Auditing

### DDE：领域分布熵

**用途：**衡量从某个源领域出发，一批原子样本生成的附加领域组合是否集中。评测单位为阶段1的选域方案，按源领域与融合域数k分组；当前每个原子样本每个k只生成一个方案，不能据此估计单个原子样本反复生成时的熵。

设固定领域全集为$\mathcal D$，数量m；源领域a；一次融合总领域数k；附加领域无序集合T满足$|T|=k-1$。

$$
M_{a,k}=\binom{m-1}{k-1},\qquad
p_{a,k}(T)=\frac{n_{a,k}(T)}{N_{a,k}},\qquad
\mathrm{DDE}_{a,k}=\frac{-\sum_Tp_{a,k}(T)\ln p_{a,k}(T)}{\ln M_{a,k}}.
$$

约定$0\ln0=0$；分母是**理论组合数**，不是观测组合数。m=7时，k=2/3/4分别有6/15/20种组合，同一公式兼容。未观察组合计零频，缺失源领域不当成熵为零；M=1时归一化熵未定义，输出null。

同时报告组合覆盖率`已观察组合数/M`；总体按源领域等权宏平均，分别报告k=2/3/4。DDE较高表示更分散，不自动代表融合更合理。

输入：阶段1`1_generate_fusion_plans` JSONL，关键字段source_domain/domain_count/fusion_domains/sample。输出：六份JSON/CSV/Markdown，含逐源领域、组合、边缘选择率和总体统计。

```bash
python3 -X utf8 "process_auditing/DDE/domain_distribution_entropy.py" \
  --input "${PIPELINE_OUTPUTS}/1_generate_fusion_plans" \
  --domain-counts 2 3 4 --output "/tmp/dde_new_run"
```

已有2100方案全量结果：k=2/3/4宏平均DDE约0.634189/0.543367/0.520369。见[使用说明](process_auditing/DDE/DDE_README.md)、[现有报告](process_auditing/DDE/DDE_outputs/dde_v4/report.md)。

### KNC：保留的保存Embedding分数覆盖指标

**用途：**不重新编码向量，直接复用阶段3候选hits里已保存的Embedding分数，衡量“已观察到相似度达标材料”的需求比例。它是保留的快速审计口径，不等于LLM蕴含判定。

对需求r，已保存且满足当前候选预算的配对集合为$E_r$，原始相似度为s。当前实现不把负余弦改成零：

$$
c_r(\tau)=\mathbf1[\exists j\in E_r:s_{rj}\ge\tau].
$$

域内需求覆盖率为$\frac1{|R|}\sum_{r\in R}c_r$，再按新增域→方案→源领域等权汇总，k分开。没有保存达标分数的需求记保存命中0，但**缺失配对的分数仍保持null，不能说材料已被证明不支持**。

同时给完整配对覆盖的保守上下界：已有达标证据为[1,1]；未达标且仍缺分数为[0,1]；所有配对已知且均未达标或明确空候选为[0,0]。上下界不是置信区间。

输入：阶段3`3_retrieve_key_fact_matches`，required_key_facts、retrieved_samples、candidate_id、hits中的method/query_index/score。输出：九份明细、manifest及报告；缺失可用率单列。

```bash
python3 -X utf8 "process_auditing/KNC/knowledge_need_coverage.py" \
  --input "${PIPELINE_OUTPUTS}/3_retrieve_key_fact_matches" \
  --samples-per-source 1 --seed 42 --threshold 0.70 \
  --output "/tmp/knc_new_run"
```

已有21方案、126需求、611/1260配对有Embedding分数；0.70下保存命中全为0。0.70未经语义标注校准，不能解释为知识支持全为0。见[说明](process_auditing/KNC/KNC_README.md)、[结果](process_auditing/KNC/KNC_outputs/knc_saved_pilot21/report.md)。

### KRC：有分数配对的条件知识需求覆盖

**用途：**按后续确认的口径，仅评测有保存分数的需求—候选配对，统一归一化分数后同时报告Binary和Weighted。**KRC与KNC的分母不同，不能直接横向比较数值。**

BM25采用独立参考样本、按目标领域固定的min/max；避免对每个需求Top-K单独归一化，导致每个需求最佳候选都变为1。余弦截断到[0,1]：

$$
b_{rj}=\operatorname{clip}_{[0,1]}\left(\frac{s^{BM25}_{rj}-m_d}{M_d-m_d}\right),\quad
e_{rj}=\operatorname{clip}_{[0,1]}(s^{cos}_{rj}),\quad
h_{rj}=\alpha b_{rj}+(1-\alpha)e_{rj}.
$$

参考范围必须有效；超出范围的分数截断并报告数量。默认α=0.5是BM25权重，阈值τ=0.5为未经过语义校准的展示门槛。RRF用于排名与候选预算诊断，不当作证据支持概率加进h。

四个模式：cosine_observed使用有Embedding的配对；hybrid_complete使用两路齐全配对；cosine_complete/bm25_complete在同一双路完整集合上做消融。仅BM25有分数而Embedding缺失的配对不进入本次评测。

给定模式与Top-K预算，令$C_r$为有效配对集合，$R^+=\{r:|C_r|>0\}$：

$$
w_r=\max_{j\in C_r}q_{rj},\qquad
\mathrm{Binary}_\tau=\frac{1}{|R^+|}\sum_{r\in R^+}\mathbf1[w_r\ge\tau],\qquad
\mathrm{Weighted}=\frac{1}{|R^+|}\sum_{r\in R^+}w_r.
$$

q是该模式的e、b或h；Weighted不先按τ筛零。上式是域内基础汇总，再按有效新增域→有效方案→源领域分层等权，k分开。无有效配对的需求排除，不能补零；同时报告纳入需求/领域/方案比例与缺失源领域。跨模式比较应使用相同支持集。

复现现有21方案时，复用包内固定抽样与归一化文件，原阶段3输入仍需另备：

```bash
python3 -X utf8 "process_auditing/KRC/KRC_evaluate.py" \
  --input "${PIPELINE_OUTPUTS}/3_retrieve_key_fact_matches" \
  --sample-manifest "process_auditing/KNC/KNC_outputs/knc_saved_pilot21/run_manifest.json" \
  --normalization "process_auditing/KRC/KRC_outputs/KRC_pilot21/KRC_normalization.json" \
  --seed 42 --alpha 0.50 --threshold 0.50 --output "/tmp/krc_new_run"
```

新数据应重新预先固定参考划分与范围，不生搬旧数据的校准文件。现有611个Embedding配对中215个双路完整，覆盖90/126需求；参考集与评测原子互斥。见[说明](process_auditing/KRC/KRC_README.md)、[现有报告](process_auditing/KRC/KRC_outputs/KRC_pilot21/KRC_report.md)。KRC_validate还会打开历史绝对路径及核对代码摘要，不是仅解压即可执行的验证入口。

### CDNS：跨域必要性、DC与IG

**用途：**固定推理模型，通过Prompt中提供或移除领域材料，观察答题是否依赖所有域。不重新训练模型；测的是指定模型、材料和Prompt下的操作性依赖，不能证明所有模型都绝对无法作答。

输入：阶段4question/options/answer和knowledge.<domain>.materials；实际pipeline没有该结构时，源域取sample，新增域默认取retrieved_samples，也支持`--materials-source used`使用实际采用材料。

每题构造Full、逐域Mask x、No Domain、逐域Only x；k域共(2+2k)条请求，2/3/4域分别6/8/10条。融合题金标和解释不进入推理Prompt；参考原子材料的问答内容作为证据。所有条件固定同一推理配置，每个条件当前只作答一次。

对Full和所有Mask结果均有效的核心完整样本集I，记答对为$y_i^F,y_i^{-d}\in\{0,1\}$：

$$
\mathrm{CDNS}=\frac1{|I|}\sum_{i\in I}y_i^F\prod_{d\in D_i}(1-y_i^{-d}),
\quad
\mathrm{IG}=\frac1{|I|}\sum_{i\in I}\left(y_i^F-\max_{d\in D_i}y_i^{-d}\right).
$$

CDNS只有Full对且每个Mask都错才计1；分母包含Full错的完整样本。IG逐题先取最佳Mask，再平均，**不是**先对每个Mask求整体正确率再取最大值；这里最佳子集仅指“移除一个域”，未遍历所有可能子集，也不是香农信息量。

对领域d出现且Full/Mask d都有效的配对集合$I_d$：

$$
\mathrm{DC}_d=\frac1{|I_d|}\sum_{i\in I_d}(y_i^F-y_i^{-d}).
$$

DC/IG保留负值；No Domain和Only作为独立诊断。ABSTAIN算不正确，超时、格式错误、缺失不算答错，排除并报告分母；没有有效样本为null。

准备与预览不调用模型：

```bash
python3 -X utf8 "process_auditing/CDNS/CDNS_prepare.py" \
  --input "${PIPELINE_OUTPUTS}/4_generate_fusion_question" \
  --difficulty easy --per-group 1 --materials-source retrieved \
  --output-dir "/tmp/cdns_prepared_new"
python3 -X utf8 "process_auditing/CDNS/CDNS_infer.py" --input-dir "/tmp/cdns_prepared_new"
```

将来真实推理（需实际服务及必要的CDNS_API_KEY；加`--execute`才发送请求）：

```bash
python3 -X utf8 "process_auditing/CDNS/CDNS_infer.py" \
  --input-dir "/tmp/cdns_prepared_new" --output "/tmp/cdns_predictions_new.jsonl" \
  --endpoint "http://127.0.0.1:8000/v1/chat/completions" \
  --model "REPLACE_MODEL" --temperature 0 --max-tokens 256 --execute
python3 -X utf8 "process_auditing/CDNS/CDNS_score.py" \
  --input-dir "/tmp/cdns_prepared_new" --predictions-file "/tmp/cdns_predictions_new.jsonl" \
  --output-dir "/tmp/cdns_scores_new"
```

输出逐样本CDNS/IG、逐域DC、各条件正确率、分组表及失败/缺失审计。目前只完成6255题字段审计和21题168请求模拟链路，**没有真实CDNS模型实验结果**。见[CDNS说明](process_auditing/CDNS/CDNS_README.md)。

## 第二层：LLM五维评审

### 五维量表

| 维度 | 核心判断 |
|---|---|
| 跨域必要性 | 每个声明领域是否不可省略；是否能靠题干、选项、常识或领域子集作答 |
| 融合依赖性 | 一个领域的信息/约束是否影响其他领域，而非独立作答后拼接 |
| 正确性与可评测性 | 条件、关键答案、推导、唯一性/允许范围和判分规则是否可靠 |
| 知识依据性 | 关键知识及其使用方式是否被可追溯材料支持 |
| 自然性与表达清晰度 | 场景是否合理，表达是否清楚且最小充分 |

0=明显不满足，1=严重缺陷，2=部分满足但有实质问题，3=合格且仅轻微问题，4=充分且证据明确。另设U：无法判断，score=null；不是0，也不算通过。服务/格式执行失败M与U分开。

**英文模板**：[共同System](llm_judge/LLM5_prompts/LLM5_system.txt)、[完整量表](llm_judge/LLM5_prompts/LLM5_rubric.md)、[阶段1](llm_judge/LLM5_prompts/LLM5_stage1.txt)、[阶段2](llm_judge/LLM5_prompts/LLM5_stage2.txt)、[第三位复核](llm_judge/LLM5_prompts/LLM5_review.txt)。当前版本LLM5-en-v2-20261005。

### 独立初审、复核与必要性约束

- J1/J2各自阶段1只看正式question/options，独立检查知识贡献、依赖与捷径，不看金标或生成器“为何跨域”的说明。
- 阶段2只接收自己的阶段1记录，再提供参考答案、明确评分契约及sample/used_samples材料，核验后给五维分数与引用。
- 任一维分差≥2、是否达到3分有分歧、任一U、关键答案/捷径/域冗余/来源矛盾进入复核。
- 一致通过样本仍按源域×k×难度分层抽查10%，非空层向上取整、固定种子。J3先独立两阶段，再看匿名P/Q，不能多数表决代替证据。
- necessity_audit=verified_shortcut时，必须给出合法、能完成实际评分任务的省域解法，必要性只能是0–2；unresolved且尚无确认反例时，必须U/null并复核。复核仍未决或存在确认关键捷径则转人工。
- 程序校验字段、引用和结论一致性；不能自动证明模型的语义推断或数学解法正确，不会擅自修改原分。

### 五维统计的分母

令P为J1/J2两个阶段均完成且结构一致的配对样本集；$V_{jd}\subseteq P$为评审j在维度d可给数值的子集。

$$
\bar s_{jd}=\frac1{|V_{jd}|}\sum_{i\in V_{jd}}s_{ijd},\quad
\mathrm{Pass}_{jd}=\frac{\sum_{i\in P}\mathbf1[s_{ijd}\ge3]}{|P|},\quad
U_{jd}=\frac{\#\{i\in P:s_{ijd}=U\}}{|P|}.
$$

均分和样本标准差排除U，标准差数值样本不足2时null；主达标率保留U在分母。分别报告J1/J2每维均分、标准差、分档比例和达标率；联合通过要求五维全部≥3，双初审联合通过要求两位都满足。数值分歧率仅用数值配对分母，U状态分歧另列；执行缺失单列，不藏进U。

J3只评选中子集，按触发/抽查/强制复核来源单列，不能与全量初审均值混合。**不把五维平均成一个总体质量分。**

### 准备与运行

在有原数据时只准备一个真实样本，不调用API：

```bash
python3 -X utf8 "llm_judge/LLM5_run.py" --smoke-one \
  --input "${PIPELINE_OUTPUTS}/4_generate_fusion_question/computer_science/test_domain_count_3.jsonl" \
  --atomic-root "${ATOMIC_ROOT}" --line 1 --output-dir "/tmp/llm5_preview_new"
```

仅用包内规范样本也可准备，无需原始语料：

```bash
python3 -X utf8 "llm_judge/LLM5_run.py" --smoke-one \
  --samples-file "llm_judge/LLM5_outputs/LLM5_deepseek_smoke2/LLM5_samples.jsonl" \
  --output-dir "/tmp/llm5_bundled_preview_new"
```

需要真实DeepSeek单题流程测试时，在上一条命令加`--execute --prompt-key`，交互隐藏输入自己的密钥。**本次打包没有执行这一步。** 同模型三角色仅验证流程，不是独立质量证据。

正式三模型评审先复制并填写[配置示例](llm_judge/LLM5_config.example.json)，使用不同模型家族及各自环境变量密钥，再运行：

```bash
python3 -X utf8 "llm_judge/LLM5_run.py" \
  --config "/path/to/LLM5_config.local.json" \
  --samples-file "llm_judge/LLM5_outputs/LLM5_deepseek_smoke2/LLM5_samples.jsonl" \
  --output-dir "/tmp/llm5_three_family_new" --execute
```

家族信息由操作者核实，配置者声明不等于程序已证明独立性；生成器家族未知时不能宣称已与生成器隔离。其他服务接口兼容性也需自行验证。

输出包括规范样本、运行清单、逐次请求/响应、最终记录、抽查/复核名单和CSV/JSON/Markdown统计。现有同一题两次真实DeepSeek流程测试中，v2第三位必要性建议从3降1，最终pending_human；模型解法有中间单位错误，两位初审仍漏判，均完整保留。见[复测报告](llm_judge/LLM5_必要性规则修复与单样本复测_20261005.md)。

## 第三层：Human Verification

**当前状态：设计和机器待核验路由已有，未开展正式人工裁决，也没有自动写入human_pass/human_fail的实现。** 以下是人工操作协议，不是已经完成的实验。

- 优先检查关键答案错误、有效单域/子集捷径、来源矛盾、专业依据不足、J3后U和联合通过结论反转；另对机器一致通过样本做预先固定的分层抽查。
- 人工先看正式题目和可见输入独立判断，再看金标、评分规则、来源和机器争议；需要时补查专业资料，并记录来源。
- 记录sample_id、样本版本/摘要、争议类型、原五维意见、人工逐维0–4/U、证据、理由、裁决者和日期、是否修订以及最终状态。
- 关键材料不足继续待核验；已确认错误/不合格可修订或舍弃。修改题目或答案生成新版本，重新走相关评审，保留原失败记录。
- 人工报告检查量、抽查方式、各结论数、未决数、修订率和机器结论推翻数；触发复核集合不是随机样本，不能将其失败率直接外推全量。

查看待人工名单：`llm_judge/LLM5_outputs/LLM5_deepseek_smoke2/LLM5_statistics/LLM5_routes.csv`。所有人工层的计数必须来自实际记录；目前机器报告中的人工裁决数为0。

## 解压后可直接执行的离线检查

以下不需要完整原始语料，不需要密钥，不调用模型。结果写入新建临时目录；若路径已存在，换一个名称。

```bash
python3 -X utf8 -m unittest discover -s "process_auditing/DDE/DDE_tests"
python3 -X utf8 -m unittest discover -s "process_auditing/KNC/KNC_tests"
python3 -X utf8 -m unittest discover -s "process_auditing/KRC/KRC_tests" -p 'KRC_test*.py'
python3 -X utf8 -m unittest discover -s "process_auditing/CDNS/CDNS_tests" -p 'CDNS_test*.py'
python3 -X utf8 -m unittest discover -s "llm_judge/LLM5_tests" -p 'LLM5_test*.py'
```

合计149项：18+28+29+22+52。它们验证实现行为，不代表真实数据质量已全部通过。

包内CDNS准备结果预览：

```bash
python3 -X utf8 "process_auditing/CDNS/CDNS_infer.py" \
  --input-dir "process_auditing/CDNS/CDNS_outputs/CDNS_prepare21"
```

包内**模拟**预测重新评分：

```bash
python3 -X utf8 "process_auditing/CDNS/CDNS_score.py" \
  --input-dir "process_auditing/CDNS/CDNS_outputs/CDNS_validation/CDNS_prepared" \
  --predictions-file "process_auditing/CDNS/CDNS_outputs/CDNS_validation/CDNS_mock_predictions.jsonl" \
  --output-dir "/tmp/cdns_bundled_mock_rescore"
```

包内LLM5第二次真实单模型记录离线重统计：

```bash
python3 -X utf8 "llm_judge/LLM5_aggregate.py" \
  --run-dir "llm_judge/LLM5_outputs/LLM5_deepseek_smoke2" \
  --output-dir "/tmp/llm5_bundled_rescore"
```

## 当前证据状态与阅读边界

| 部分 | 已完成 | 未完成/不能声称 |
|---|---|---|
| DDE | 2100真实方案的全量选域分布审计 | 单题知识正确性判断 |
| KNC/KRC | 同一21方案的纯离线保存分数审计、缺失诊断 | 相似度等于充分支持；全量语义质量结论 |
| CDNS | 代码、数据适配、模拟端到端和评分 | 真实模型遮蔽实验 |
| LLM5 | 英文Prompt、流程实现、同题两轮DeepSeek测试 | 三家族独立验证、全量评分 |
| Human Verification | 流程设计与pending_human名单 | 已完成实际人工裁决 |

ZIP含有现有评测明细和内嵌样本，并非只包含空模板。完整语料和模型凭据需另行准备；不提供密钥或权重。原始来源文档中未随包提供的链接已标记，当前命令以本文为准。

当前文件清单与SHA256见`PACKAGE_MANIFEST.json`；打包/解压验证结果见`PACKAGE_VALIDATION.json`。压缩包旁的`.sha256`用于核对整个ZIP。历史输出不因目录迁移而改写，旧运行路径与旧代码摘要继续作为历史记录保留。
