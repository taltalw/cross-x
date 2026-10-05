# Process Auditing 指标导航

各指标的代码、运行脚本、说明、测试和历史结果分别放入所属目录。此次整理只调整文件位置与引用，不修改指标定义、计算口径或历史评测结果。

| 指标 | 使用说明 | 示例脚本 | 测试 | 历史输出 |
|---|---|---|---|---|
| DDE：领域分布熵 | [DDE_README](DDE/DDE_README.md) | [run_dde_example.sh](DDE/run_dde_example.sh) | DDE/DDE_tests | [DDE_outputs](DDE/DDE_outputs) |
| KNC：保存Embedding分数的知识需求覆盖 | [KNC_README](KNC/KNC_README.md) | [run_knc_example.sh](KNC/run_knc_example.sh) | KNC/KNC_tests | [KNC_outputs](KNC/KNC_outputs) |
| KRC：有分数配对的条件知识需求覆盖 | [KRC_README](KRC/KRC_README.md) | [KRC_run_example.sh](KRC/KRC_run_example.sh) | KRC/KRC_tests | [KRC_outputs](KRC/KRC_outputs) |
| CDNS：Prompt材料遮蔽的跨域必要性 | [CDNS_README](CDNS/CDNS_README.md) | [CDNS_run_example.sh](CDNS/CDNS_run_example.sh) | CDNS/CDNS_tests | [CDNS_outputs](CDNS/CDNS_outputs) |

```text
process_auditing/
├── README.md
├── .gitignore
├── DDE/
│   ├── domain_distribution_entropy.py
│   ├── run_dde_example.sh
│   ├── DDE_README.md
│   ├── DDE_tests/
│   └── DDE_outputs/
├── KNC/
│   ├── knc_saved_core.py
│   ├── knowledge_need_coverage.py
│   ├── plot_knc_saved_scores.py
│   ├── run_knc_example.sh
│   ├── KNC_README.md
│   ├── KNC_tests/
│   └── KNC_outputs/
├── KRC/
│   ├── KRC_*.py / KRC_run_example.sh / KRC_README.md
│   ├── KRC_tests/
│   └── KRC_outputs/
└── CDNS/
    ├── CDNS_*.py / CDNS_run_example.sh / CDNS_README.md
    ├── CDNS_tests/
    └── CDNS_outputs/
```

Python生成的`__pycache__`留在所属指标目录内，由统一`.gitignore`忽略。四个历史输出目录同样默认忽略，文件仍保留在本地。

## 常用结果入口

- [DDE全量2100方案报告](DDE/DDE_outputs/dde_v4/report.md)
- [DDE计算机三域100方案报告](DDE/DDE_outputs/dde_cs_k3/report.md)
- [KNC七源21方案报告](KNC/KNC_outputs/knc_saved_pilot21/report.md)
- [KNC单源3方案报告](KNC/KNC_outputs/knc_saved_smoke3/report.md)
- [KRC七源21方案报告](KRC/KRC_outputs/KRC_pilot21/KRC_report.md)

## 离线运行与测试

从仓库根目录 `/home/zhangpengyue/benchmark/cross-x` 运行。以下命令使用新的输出目录，不覆盖已有历史结果；同名目录已有结果时另选名称。

```bash
bash "knowledge/verification/process_auditing/DDE/run_dde_example.sh" \
  --output "knowledge/verification/process_auditing/DDE/DDE_outputs/dde_new"

bash "knowledge/verification/process_auditing/KNC/run_knc_example.sh" \
  --output "knowledge/verification/process_auditing/KNC/KNC_outputs/knc_saved_new"

bash "knowledge/verification/process_auditing/KRC/KRC_run_example.sh" \
  --output "knowledge/verification/process_auditing/KRC/KRC_outputs/KRC_new"
```

DDE/KNC/KRC命令仅读取现有pipeline输出，不运行模型。CDNS的准备、模拟验证、实际推理等操作有不同入口，见其使用说明。

原有测试按指标分别运行：

```bash
python3 -X utf8 -m unittest discover -s "knowledge/verification/process_auditing/DDE/DDE_tests" -v
python3 -X utf8 -m unittest discover -s "knowledge/verification/process_auditing/KNC/KNC_tests" -v
python3 -X utf8 -m unittest discover -s "knowledge/verification/process_auditing/KRC/KRC_tests" -p 'KRC_test*.py' -v
python3 -X utf8 -m unittest discover -s "knowledge/verification/process_auditing/CDNS/CDNS_tests" -p 'CDNS_test*.py' -v
```

## 历史：2026-10-05指标内归类对应关系

下表路径均相对于本目录。原源码、脚本和结果文件名保持不变。

| 原位置 | 新位置 |
|---|---|
| domain_distribution_entropy.py | DDE/domain_distribution_entropy.py |
| run_dde_example.sh | DDE/run_dde_example.sh |
| DDE_README.md | DDE/DDE_README.md |
| tests/test_domain_distribution_entropy.py | DDE/DDE_tests/test_domain_distribution_entropy.py |
| outputs/dde_v4 | DDE/DDE_outputs/dde_v4 |
| outputs/dde_cs_k3 | DDE/DDE_outputs/dde_cs_k3 |
| knc_saved_core.py | KNC/knc_saved_core.py |
| knowledge_need_coverage.py | KNC/knowledge_need_coverage.py |
| plot_knc_saved_scores.py | KNC/plot_knc_saved_scores.py |
| run_knc_example.sh | KNC/run_knc_example.sh |
| KNC_README.md | KNC/KNC_README.md |
| tests/test_knc_saved_scores.py | KNC/KNC_tests/test_knc_saved_scores.py |
| outputs/knc_saved_pilot21 | KNC/KNC_outputs/knc_saved_pilot21 |
| outputs/knc_saved_smoke3 | KNC/KNC_outputs/knc_saved_smoke3 |

KNC仍复用DDE模块中的领域全集和输入校验函数，导入路径已同步调整。KRC示例脚本固定抽样清单改为`KNC/KNC_outputs/knc_saved_pilot21/run_manifest.json`。相关运行命令和说明链接已同步更新。

历史JSON中的运行时路径和代码摘要保留原值，以反映当时的运行环境；不能将其中的旧位置当作当前启动路径。40份迁移的历史文件逐字节未变，连同原有KRC/CDNS输出共96份历史文件SHA256核对一致。

工作区根目录的既有专题设计文档保留原位置，其中受影响的KNC使用说明只修正路径。`llm_judge`与本目录在verification内并列；完整阅读入口见上级综合指南。

## 历史：指标内归类验证结果

- 原有97项测试全部通过：DDE18、KNC28、KRC29、CDNS22。
- 从`/tmp`工作目录实际运行DDE/KNC/KRC示例脚本，验证输入定位与KRC对KNC清单的引用；输出写临时目录，模型调用0。
- DDE全量2100方案的6份报告、KNC21方案的9份报告均与历史文件逐字节一致。
- KRC21方案的指标与归一化参数一致；两份JSON仅清单新位置及归一化来源记录不同：默认脚本重新计算同一参考参数，历史运行曾读取已保存的参数文件。
- 文档链接、Shell语法、包导入与直接脚本入口验证通过。

完整迁移清单与历史哈希（原工作区来源，未随包提供：`../../../.helloagents/archive/2026-10/202610050856_process-auditing-layout/migration_manifest.json`）、验收记录（原工作区来源，未随包提供：`../../../.helloagents/archive/2026-10/202610050856_process-auditing-layout/verification.json`）已归档在工作区知识库。

## 本次整体迁入verification

本目录现位于`knowledge/verification/process_auditing`，与`llm_judge`并列；目录名已统一为`process_auditing`。新增`design_docs/`收录整体设计、当前公式、历史提案及附图；原工作区设计文件继续保留。

默认输入路径已适配新增层级，包外重算通过`--input`指定数据。整包149项离线测试通过，四个指标默认路径验证通过；包括LLM5在内的179份历史输出哈希不变。综合说明及解压后命令见[上级指南](../三层审计与LLM五维评分_综合阅读指南.md)，详细验收见[PACKAGE_VALIDATION.json](../PACKAGE_VALIDATION.json)。
