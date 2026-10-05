# KRC：仅有分数配对的条件覆盖审计

Python 3.10+，评测和独立核验仅标准库；可选绘图使用matplotlib。所有交付文件与输出均以KRC_开头。

完整公式和真实结果：[KRC实现与评测说明](../design_docs/KRC_实现与评测说明_20261005.md)。旧设计的缺失贡献下界已由用户最新要求替代；当前不补零。

## 快速复现

从任意目录运行：

```bash
bash "/home/zhangpengyue/benchmark/cross-x/knowledge/verification/process_auditing/KRC/KRC_run_example.sh" --overwrite
```

输入默认是 `knowledge/pipielines_v4/outputs/3_retrieve_key_fact_matches`。脚本固定使用之前的 `../KNC/KNC_outputs/knc_saved_pilot21/run_manifest.json`，复现同一7原子、21方案和611个Embedding配对。输出默认在本目录 `KRC_outputs/KRC_pilot21/`。

参考集140原子、420方案，与全部固定评测原子互斥。先读取并验证2100输入方案，再拟合参考分数范围、评测选中21方案；没有运行全量1680留出方案的评测。BM25参考拟合使用参考集已保存BM25分数，不要求参考配对也有Embedding；实际被评分的配对必须有Embedding。

主阈值0.50，BM25权重0.50，阈值网格0.20–0.80，预算1/3/5/10/all。阈值未经人工支持标签校准。

首次使用新输出目录无需--overwrite；已有12份基础报告默认受保护。设置 `PYTHON_BIN` 可指定Python解释器。

## 四个模式和分母

| 模式 | 评分配对 | 配对分数 |
|---|---|---|
| cosine_observed | Embedding可用 | clip(Cosine,0,1) |
| hybrid_complete | Embedding和BM25都可用 | α×BM25_norm+(1−α)×Cosine_norm |
| cosine_complete | 与混合相同 | Cosine_norm |
| bm25_complete | 与混合相同 | BM25_norm |

每项需求对有效材料取最大值。无有效材料的需求weight=None、covered=None，并排除出当前模式条件均值；真实零分仍纳入。先平均领域内有效需求，再平均有效新增领域、有效方案、源领域。没有数据的源领域不会被当零分，完整七领域macro为N/A，另报局部observed_source均值。

配对数不是分母：611个Embedding配对对应126项需求；215个双路配对对应90项需求。混合结果不能解释为126项需求的总体覆盖。

预算先按原RRF顺序取前K，再筛选有效配对；不重新排序补足K个有分数候选。预算改变时，条件分母会变化，所以条件均值不保证单调。单项已有有效需求的最佳分数随预算增加不下降。

RRF只决定原候选顺序，需求级RRF贡献作为诊断列输出，不加进默认混合分数。完整加权值不依赖阈值，汇总CSV为便于并列展示会按阈值重复，不能跨阈值累加。

## 命令示例

以下相对路径命令从仓库根目录 `/home/zhangpengyue/benchmark/cross-x` 执行。

复现3方案冒烟测试；它只含computer_science，完整七源宏平均N/A，局部结果见CSV：

```bash
bash "knowledge/verification/process_auditing/KRC/KRC_run_example.sh" \
  --source-domains computer_science \
  --output "knowledge/verification/process_auditing/KRC/KRC_outputs/KRC_smoke3" --overwrite
```

使用已保存的归一化文件进行另一次试运行：

```bash
bash "knowledge/verification/process_auditing/KRC/KRC_run_example.sh" \
  --normalization "knowledge/verification/process_auditing/KRC/KRC_outputs/KRC_smoke3/KRC_normalization.json" \
  --output "knowledge/verification/process_auditing/KRC/KRC_outputs/KRC_reproduce21"
```

工具核对归一化与当前输入哈希、参考划分、配置完全一致；不允许输出覆盖传入的归一化文件。读取缓存参数时会复算参考范围核验，成本只是标准库分数统计。

更换主展示阈值，仍保留完整敏感性网格：

```bash
bash "knowledge/verification/process_auditing/KRC/KRC_run_example.sh" --threshold 0.30 \
  --output "knowledge/verification/process_auditing/KRC/KRC_outputs/KRC_tau030"
```

扩大为每源领域5个共享原子样本、105方案时，直接调用Python入口，省略固定旧21样本清单：

```bash
python -X utf8 "knowledge/verification/process_auditing/KRC/KRC_evaluate.py" \
  --input "knowledge/pipielines_v4/outputs/3_retrieve_key_fact_matches" \
  --samples-per-source 5 --seed 42 \
  --output "knowledge/verification/process_auditing/KRC/KRC_outputs/KRC_pilot105"
```

注意：参考集选择会排除所有指定评测原子。若改变抽样数量或固定样本，参考范围可能随之变化，不能假定仍是本次归一化配置。比较结果时核对normalization_id。本次示例脚本固定旧清单时，--samples-per-source不会覆盖该清单。

计算当前固定参考划分外的全部1680方案（本次未运行）：

```bash
bash "knowledge/verification/process_auditing/KRC/KRC_run_example.sh" --all-evaluation \
  --output "knowledge/verification/process_auditing/KRC/KRC_outputs/KRC_all1680"
```

这种方式保持与21方案完全相同的参考划分与normalization_id。全量会输出更大的明细，请使用独立目录。

## 基础输出：12份，全部KRC_前缀

| 文件 | 内容 |
|---|---|
| KRC_pair_scores.csv | 仅Embedding可用配对，原始分数、归一化分数、双路可用性、融合分数 |
| KRC_requirement_scores.csv | 全部需求×模式×预算，最佳有效分数/材料原文、有效配对数、排除状态 |
| KRC_requirement_coverage.csv | 全部需求×模式×预算×阈值，covered为0/1/null |
| KRC_per_domain.csv | 每方案新增领域条件统计与需求分母 |
| KRC_per_plan.csv | 方案条件统计，含总/有效领域及需求数 |
| KRC_per_source.csv | 源领域×k×模式×预算×阈值统计 |
| KRC_summary.csv | 各k宏平均、局部均值、需求与配对纳入率 |
| KRC_summary.json | 全部明细、统计、归一化参数与清单 |
| KRC_run_manifest.json | 输入及代码哈希、参考/评测样本、参数、历史检索配置 |
| KRC_normalization.json | 固定参考范围、参考身份与输入哈希 |
| KRC_reference_manifest.json | 参考样本及原子划分 |
| KRC_report.md | 中文结果解读 |

缺失值：JSON中null，CSV中空白。主需求数统计应筛选一个mode与budget，不能跨模式、预算重复计数。核对原始材料可通过manifest的input_file和input_line定位。

输入JSONL支持UTF-8/BOM/CRLF及正文Unicode分隔符；重复方案、候选ID、冲突hit、非法数值/需求索引/排名报错。不允许输出放进原始输入目录，保护已有报告和输入文件。

## 独立复核与绘图

独立校验读取原始JSONL，复算参考范围、权重和分层汇总，不导入评测实现；输出额外的KRC_validation.json：

```bash
python -X utf8 "knowledge/verification/process_auditing/KRC/KRC_validate.py" \
  --input "knowledge/verification/process_auditing/KRC/KRC_outputs/KRC_pilot21/KRC_summary.json"
```

使用本机已有绘图环境，不联网安装：

```bash
"/tmp/process_auditing_plot_20261005/bin/python" -X utf8 \
  "knowledge/verification/process_auditing/KRC/KRC_plot.py" \
  --input "knowledge/verification/process_auditing/KRC/KRC_outputs/KRC_pilot21/KRC_summary.json"
```

临时环境若已删除，可换成任意已安装matplotlib的Python。生成KRC_figures下三组PNG/PDF/SVG：Binary阈值、同支持集Weighted、纳入率。绘图和独立核验分别覆盖其管理的同名衍生文件，评测入口只覆盖12份基础报告。

## 测试

```bash
python -X utf8 -m unittest discover \
  -s "knowledge/verification/process_auditing/KRC/KRC_tests" -p "KRC_test*.py" -v
bash -n "knowledge/verification/process_auditing/KRC/KRC_run_example.sh"
```

KRC新增29项测试；CLI集成测试在python -S下运行，不依赖第三方库或模型。当前21方案的混合Weighted为0.249924/0.240409/0.260760，@0.50的Binary为0%/0%/1.59%，有效需求数17/30/43。完整结果见 [KRC_report.md](KRC_outputs/KRC_pilot21/KRC_report.md)。
