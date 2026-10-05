# KNC-Emb-Saved：复用阶段3分数的纯离线审计

直接读取已有 embedding hits，不加载模型、不读向量库、不联网。评测使用 Python 3.10+ 标准库；只有可选绘图需要 matplotlib。

完整设计：[纯离线保存分数方案](../design_docs/知识需求覆盖率_KNC_纯离线保存分数方案_20261005.md)。LLM Judge 方案独立保留。

## 快速运行

从任意目录复现21方案小样本：

```bash
bash "/home/zhangpengyue/benchmark/cross-x/knowledge/verification/process_auditing/KNC/run_knc_example.sh" --overwrite
```

默认输入是 `../../../pipielines_v4/outputs/3_retrieve_key_fact_matches/`，默认输出是本目录 `KNC_outputs/knc_saved_pilot21/`。已有结果需 `--overwrite`；第一次写新目录不需要。

默认每源领域抽一个在k=2/3/4中共有的原子样本，固定seed=42，形成7原子样本、21方案。程序先读取并验证输入全部2100记录，再对选中21方案统计。它不会重新运行pipeline。

如要指定Python，在命令前设置 `PYTHON_BIN=/path/to/python`。

## 其他命令

以下Python命令在仓库根目录 `/home/zhangpengyue/benchmark/cross-x` 执行。

单源领域3方案冒烟测试（完整七领域宏平均会是N/A，查看局部均值）：

```bash
bash "knowledge/verification/process_auditing/KNC/run_knc_example.sh" \
  --source-domains computer_science \
  --output "knowledge/verification/process_auditing/KNC/KNC_outputs/knc_saved_smoke3" --overwrite
```

单个三域JSONL，计算该文件全部方案：

```bash
python -X utf8 "knowledge/verification/process_auditing/KNC/knowledge_need_coverage.py" \
  --input "knowledge/pipielines_v4/outputs/3_retrieve_key_fact_matches/medical/test_domain_count_3.jsonl" \
  --domain-counts 3 --all-plans \
  --output "knowledge/verification/process_auditing/KNC/KNC_outputs/knc_saved_medical_k3"
```

扩展到105方案，仍按源领域配对抽样：

```bash
bash "knowledge/verification/process_auditing/KNC/run_knc_example.sh" \
  --samples-per-source 5 \
  --output "knowledge/verification/process_auditing/KNC/KNC_outputs/knc_saved_pilot105"
```

全量2100方案（本次未运行；会生成更大的逐需求/配对明细）：

```bash
bash "knowledge/verification/process_auditing/KNC/run_knc_example.sh" --all-plans \
  --output "knowledge/verification/process_auditing/KNC/KNC_outputs/knc_saved_all2100"
```

自定义敏感性网格；主阈值自动加入网格，all自动加入候选预算：

```bash
bash "knowledge/verification/process_auditing/KNC/run_knc_example.sh" \
  --threshold 0.70 --thresholds 0.20 0.25 0.30 0.35 0.40 0.50 0.70 \
  --budgets 1 3 5 10 \
  --output "knowledge/verification/process_auditing/KNC/KNC_outputs/knc_saved_custom"
```

## 输入约定

| 输入 | 要求 |
|---|---|
| 文件结构 | UTF-8 JSONL文件或可递归发现JSONL的目录；允许BOM、CRLF |
| 方案身份 | source_domain、domain_count、fusion_domains、sample.prompt/completion |
| 需求 | 每新增领域非空required_key_facts列表；每项含非空key_fact、necessity |
| 候选 | retrieved_samples包含全部新增领域；允许明确的空列表 |
| 命中 | candidate_id、sample、hits；embedding hit包含从1开始的query_index及[-1,1]有限score |
| 配置 | retrieval.method=hybrid，非空embedding_config_hash；选中方案不得混合相关配置 |

只在同一新增领域内匹配需求与候选。非embedding的hits忽略，不将BM25、RRF当相似度。不加载阶段4最终题目，不混入难度变体。

输入目录内的所有JSONL均会被校验；需要只处理某个文件时直接指定该文件。不存在的源领域、无法跨k配对的样本、重复方案和冲突分数会报错退出，避免静默丢数据。

## 指标口径

对每项需求，取**已保存**embedding分数的最大值，若≥阈值则保存命中为1，否则0。分母为全部需求。依次对“领域内需求→新增领域→同源方案→源领域”平均；k=2、3、4分开输出。

缺失分数本身保持None；保存命中为0只表示没有观察到达标记录。无保存命中而仍有配对缺失，完整配对覆盖状态为unknown，界限[0,1]。已观察到达标则[1,1]，全部配对已知且低于阈值则[0,0]。空候选没有可覆盖的材料，界限[0,0]。

保存命中率是完整配对相似度覆盖的保守下界；不是语义充分支持率。保守区间不是置信区间。

默认领域全集为chemistry、computer_science、financial、geography、legal、mathematics、medical。缺少任何源领域时，完整macro列为null/N/A，同时保留observed_source列。`--source-domains`不会改变宏平均的领域全集。

## 九份输出

| 文件 | 粒度及主要内容 |
|---|---|
| pair_scores.csv | 每需求×保留候选；embedding_score与observed/not_saved |
| requirement_scores.csv | 每需求×预算；key_fact、necessity、最佳分数/候选ID/问答、observed_pairs与missing_pairs |
| requirement_coverage.csv | 每需求×预算×阈值；saved_hit、complete_state、complete_lower/upper |
| per_plan.csv | 每方案×预算×阈值；knc_saved、界限、需求/配对可用率、all_covered_saved、weakest_domain_saved |
| per_source.csv | 每源领域×k×预算×阈值；等权方案均值、n_plans、n_needs |
| summary.csv | 每k×预算×阈值；macro_*、observed_source_*、missing_sources |
| summary.json | 上述所有表及manifest的完整JSON，缺失分数为null |
| run_manifest.json | 输入路径/哈希、参数、历史模型配置、选中方案/原子ID/文件行号 |
| report.md | 中文结果与解读限制 |

CSV缺失数值为空。`budget=all`是实际全部保留候选，数字预算表示输入列表前缀，保持原RRF顺序。`requirement_scores.csv`按预算重复需求，统计需求数时必须筛选预算，通常使用all。threshold明细同理不要跨阈值重复计数。

使用requirement_id连接两个需求表；使用plan_id连接逐方案表和manifest样本清单。需要融合任务完整上下文时，根据manifest里的input_file与input_line回到原始JSONL查看question_plan。

输出目录不能在原始输入目录中。默认保护已有九份报告，`--overwrite`只覆盖这些报告；绘图脚本单独覆盖它管理的同名图像。

## 当前已完成的小样本

21方案、126需求；所有需求均有分数，但只有611/1260配对有保存分数。最佳保存分数范围0.145658–0.404975。

| k | 方案/需求 | @0.70 | @0.30 | @0.40 |
|---|---|---:|---:|---:|
| 2 | 7/21 | 0% | 9.52% | 0% |
| 3 | 7/42 | 0% | 9.52% | 0% |
| 4 | 7/63 | 0% | 12.70% | 1.59% |

0.70未校准，零保存命中不等于零知识支持。完整配对在该阈值的保守界限均为[0%,100%]。这是工具试运行，不能据此比较总体数据质量。

查看 [report.md](KNC_outputs/knc_saved_pilot21/report.md)。本次另完成3方案冒烟测试，没有运行105/2100方案评测。

## 可选绘图

现有机器已具备绘图环境，可离线使用；评测代码不依赖它：

```bash
"/tmp/process_auditing_plot_20261005/bin/python" -X utf8 \
  "knowledge/verification/process_auditing/KNC/plot_knc_saved_scores.py" \
  --input "knowledge/verification/process_auditing/KNC/KNC_outputs/knc_saved_pilot21/summary.json"
```

临时环境将来若不存在，可使用任意已经安装matplotlib的Python解释器替换路径。无需模型库。

输出在JSON旁的figures目录，每组包含PNG、PDF、SVG：

- knc_threshold_and_scores：阈值敏感性及已观察最佳分数ECDF。
- knc_score_availability：需求/配对保存分数可用率，使用实际计数。
- knc_candidate_budget：固定阈值的预算曲线，默认0.30；可传`--budget-threshold 0.70`，必须是JSON已有阈值。

图轴使用英文以便导出；局部源领域输入明确标记observed sources only。保存分数缺失的不进入ECDF，图例显示可用数/总需求数。

## 测试

```bash
python -X utf8 -m unittest discover -s "knowledge/verification/process_auditing/KNC/KNC_tests" -v
bash -n "knowledge/verification/process_auditing/KNC/run_knc_example.sh"
```

本目录独立运行KNC28项测试；DDE18项测试见上级DDE目录。测试包括禁用第三方site包的CLI运行、禁用socket连接的执行、JSONL Unicode分隔符回归、缺失分数/阈值边界、多领域/多源平均与文件保护。
