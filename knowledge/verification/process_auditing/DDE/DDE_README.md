# 领域分布熵 DDE：实现、输入输出与运行示例

该工具计算当前 pipeline 在阶段1选择领域时的**领域组合分布熵**，支持双域、三域、四域，使用 Python 3.10+ 标准库。无需安装第三方包，无需 GPU 或模型 API。

## 先运行哪个文件？

运行程序：`domain_distribution_entropy.py`。

传给程序的数据目录：

```text
/home/zhangpengyue/benchmark/cross-x/knowledge/pipielines_v4/outputs/1_generate_fusion_plans/
```

它会递归读取目录下所有 `.jsonl` 文件。当前包含 7 个源领域 × 3 种融合规模 = 21 个文件，每文件 100 条方案，总计 2100 条。

例如：

```text
1_generate_fusion_plans/
├── chemistry/
│   ├── test_domain_count_2.jsonl
│   ├── test_domain_count_3.jsonl
│   └── test_domain_count_4.jsonl
├── computer_science/
│   └── ...
└── ...
```

- `domain_count=2`：源领域 A + 1 个附加领域。
- `domain_count=3`：源领域 A + 2 个附加领域。
- `domain_count=4`：源领域 A + 3 个附加领域。

`atomic/` 和 `0_extract_key_facts/` 没有生成后的选域结果，不能直接作为本指标输入。

`4_generate_fusion_question/` 将方案展开为不同难度的题目，直接计数会改变统计单位。程序拒绝带 `difficulty` 的最终题目记录，也会拒绝同一个源样本在相同 k 下重复出现。

本工具统计的是阶段1的选域分布。如要研究最终验收后入库数据的领域分布，应先按明确的方案标识去重并建立独立评测口径，不能把这里的结果直接称为最终入库分布。

## 一条输入包含什么？

输入是 JSONL：每行一个 JSON 对象。下面是字段示意，`prompt` 和 `completion` 的内容为占位说明，不是实际题目：

```json
{"source_domain":"computer_science","domain_count":3,"fusion_domains":["mathematics","financial"],"sample":{"prompt":"源原子问题全文","completion":"源原子答案全文"}}
```

| 字段 | 含义 | 用途 |
|---|---|---|
| `source_domain` | 原子样本所属的源领域 A | 决定统计分组 |
| `domain_count` | 包含 A 在内的总领域数 k | 分别统计双域、三域、四域 |
| `fusion_domains` | 除 A 之外的 k−1 个领域 | 形成无序组合 T |
| `sample.prompt` | 原子样本的问题文本 | 与答案共同识别源样本 |
| `sample.completion` | 原子样本的答案文本 | 检测重复记录 |

现有阶段1文件中的 `question_plan`、`answer_plans`、`key_facts` 等字段可以保留；本指标无需读取其语义内容。

`["mathematics", "financial"]` 和 `["financial", "mathematics"]` 被计为同一组合。领域不能重复，也不能包含源领域本身。

重复记录按 `(source_domain, domain_count, sample.prompt, sample.completion)` 判断。相同样本出现在不同 k 中合法；同一个 k 下重复出现会报错并显示文件和行号。当前实现面向现有 pipeline 的“一原子样本、每个 k 一个方案”设计；如果未来有意对同一样本多次独立采样，需要新增明确的采样标识与统计口径。

## 使用的公式

固定领域全集大小为 m。对源领域 a 和融合规模 k：

$$
\mathcal T_{a,k}=\{T\subseteq\mathcal D\setminus\{a\}:|T|=k-1\},
\qquad M_{a,k}=\binom{m-1}{k-1}.
$$

$$
p_{a,k}(T)=\frac{n_{a,k}(T)}{N_{a,k}},
\qquad
\mathrm{DDE}_{a,k}=
\frac{-\sum_{T\in\mathcal T_{a,k}}p_{a,k}(T)\ln p_{a,k}(T)}{\ln M_{a,k}}.
$$

约定 `0 ln 0 = 0`；对非空分组且 M>1，归一化熵在 0 到 1 之间（浮点计算可能有极小舍入误差）。分布集中在单一组合时为 0，在所有理论组合上均匀分布时为 1。

**分母使用理论组合数，不是实际出现的组合数。** 当前 m=7，因此 k=2、3、4 的分母分别是 `ln 6`、`ln 15`、`ln 20`。

源领域齐全时，总体指标按源领域等权平均：

$$
\mathrm{DDE}_k=\frac{1}{m}\sum_{a\in\mathcal D}\mathrm{DDE}_{a,k}.
$$

不把所有源领域混在一起计算一个熵，也不按源领域样本数加权。默认领域全集是：

```text
chemistry computer_science financial geography legal mathematics medical
```

这对应当前七领域均可作为源领域、其余六领域均可作为附加领域的评测设定。如果未来存在事先规定的选域禁配规则，需要显式重新定义可选组合空间。

辅助指标：

- `coverage = observed_combinations / possible_combinations`：出现过的组合占所有理论组合的比例。
- `inclusion_rate(a,b,k)`：源领域 a 的方案中包含目标领域 b 的比例；对所有 b 求和为 k−1。
- `slot_probability(a,b,k)`：该领域的计数除以 N(k−1)；对所有 b 求和为 1。
- `marginal_dde`：按 `slot_probability` 计算、用 `ln(m−1)` 归一化的边缘熵。它是辅助诊断项；不同组合分布可以有相同边缘分布，故不能替代组合熵。

## 推荐命令：直接评测当前数据

从任意工作目录运行：

```bash
bash "/home/zhangpengyue/benchmark/cross-x/knowledge/verification/process_auditing/DDE/run_dde_example.sh" --overwrite
```

`--overwrite` 允许重新生成六份审计报告；首次运行且输出不存在时可省略。当前已运行过一次，所以复制上面的命令可以直接复现。

默认报告目录：

```text
/home/zhangpengyue/benchmark/cross-x/knowledge/verification/process_auditing/DDE/DDE_outputs/dde_v4/
```

示例脚本默认使用 `python3`。如需指定环境：

```bash
PYTHON_BIN="/path/to/venv/bin/python" bash "/home/zhangpengyue/benchmark/cross-x/knowledge/verification/process_auditing/DDE/run_dde_example.sh" --overwrite
```

也可以从项目目录直接调用 Python：

```bash
cd "/home/zhangpengyue/benchmark/cross-x"
python3 -X utf8 knowledge/verification/process_auditing/DDE/domain_distribution_entropy.py \
  --input knowledge/pipielines_v4/outputs/1_generate_fusion_plans \
  --output knowledge/verification/process_auditing/DDE/DDE_outputs/dde_v4 \
  --domain-counts 2 3 4 \
  --overwrite
```

## 只测试一个真实文件

例如只统计“计算机科学作为源领域的三域融合方案”：

```bash
cd "/home/zhangpengyue/benchmark/cross-x"
python3 -X utf8 knowledge/verification/process_auditing/DDE/domain_distribution_entropy.py \
  --input knowledge/pipielines_v4/outputs/1_generate_fusion_plans/computer_science/test_domain_count_3.jsonl \
  --output knowledge/verification/process_auditing/DDE/DDE_outputs/dde_cs_k3 \
  --domain-counts 3 \
  --overwrite
```

这时固定领域全集仍为七领域，因为这个源领域仍有六个可选附加领域。**不要为了只测试一个源领域而缩小 `--domains`。**

该文件包含 100 条方案，计算机科学分组 DDE 约为 `0.3987`。`per_source.csv` 中其他六个源领域标为 `missing`；`summary.csv` 中完整 `macro_dde` 为空，`observed_source_macro_dde` 为约 `0.3987`。局部输入不能代表七源领域的总体均值。

## 输出是什么？

| 文件 | 内容 | 建议用途 |
|---|---|---|
| `report.md` | 中文汇总、逐源领域表和阅读说明 | 首先打开它理解结果 |
| `summary.csv` | 每个 k 一行，包含方案数、完整宏平均 DDE、局部均值和宏平均覆盖率 | 论文总体表或 DDE 柱状图 |
| `per_source.csv` | 每个源领域×k 一行，包含原始熵、DDE、覆盖率和状态 | 比较不同源领域的选择偏好 |
| `combinations.csv` | 每个源领域×k×附加领域组合的计数和概率，包含零频次组合 | 组合频次图、组合分布排查 |
| `selection_rates.csv` | 每个源领域×k×目标领域的出现次数、出现率和槽位概率 | 分 k 画源领域×目标领域热图 |
| `summary.json` | 上述完整统计、固定领域全集、输入路径、行数和输入文件 SHA256 | 程序读取、实验复现 |

对于当前完整七领域数据，输出包括 3 行汇总、21 行源领域统计、287 行组合统计及 126 行领域选择率统计（均不含 CSV 表头）。

`summary.json` 结构：

```text
schema_version, domains, domain_counts, definition
metadata: input_path, files[{path, sha256, rows}], rows_read,
          rows_included, rows_excluded_by_k, blank_lines
summary_by_k: [每个 k 的总体统计]
per_source: [源领域×k 的统计]
combinations: [组合计数与概率]
selection_rates: [目标领域选择率]
```

缺失值在 JSON 中为 `null`，CSV 中为空，Markdown 中为 `N/A`。缺失值不能解释为“熵为零”。

运行状态：成功退出码为 0；无效输入、重复记录、目录错误或未允许的覆盖等错误退出码为 2。验证输入后才写报告；默认不覆盖已有报告，不允许将报告目录放入批量输入目录内部。

## 当前数据实测结果

2026-10-05 对现有阶段1目录实测；每个源领域、每个 k 有 100 条方案：

| 融合规模 k | 方案数 | 每个源领域理论组合数 | 宏平均 DDE | 宏平均组合覆盖率 |
|---|---:|---:|---:|---:|
| 2 | 700 | 6 | 0.634189 | 88.10% |
| 3 | 700 | 15 | 0.543367 | 60.00% |
| 4 | 700 | 20 | 0.520369 | 51.43% |

这些数值与此前 `process_auditing_design_assets_20261005/descriptive_statistics.json` 中的组合熵及覆盖率一致。

它们表明当前三域、四域方案在各自组合空间中的分布更集中；**不能据此直接判断题目质量更差**。DDE 反映选域多样性，不负责判断融合是否合理。不同 k 的理论组合数和有限样本偏差也不同，比较时应同时报告 N、理论组合数和覆盖率；本程序报告经验分布的插件估计，不做熵偏差修正或显著性检验。

目前一个源原子样本在每个 k 下只有一次选域结果，不能估计该原子样本重复采样时的熵。这里评测的是同一源领域的一批原子样本生成方案的分布。

## 边界行为与参数

- 输入可以是单个文件或目录，目录递归读取所有 `.jsonl`。请传阶段1目录，不要传整个 `outputs/`。
- 默认统计 k=2、3、4。`--domain-counts 3` 只纳入三域方案，其他合法记录计入 `rows_excluded_by_k`。输入记录均需满足字段校验。
- `--domains A B C D` 可显式声明其他固定全集，同时按需求配置 `--domain-counts`。更改全集会改变分母，只应在评测任务本身更换全集时使用。
- 若 k=m，每个源领域只剩一个理论组合。此时原始熵为 0、覆盖率为 1，但归一化分母为 0，DDE 为 `null`。
- 若某个源领域没有数据，其熵与覆盖率均为 `null`；完整宏平均 DDE 也为 `null`，单独报告已观察源领域的均值。
- 若完全没有可纳入的记录，直接报错，不生成一个伪零分报告。
- 不提供自动删重：重复或相互冲突的方案需明确选择实验批次后再评测。
- 默认报告目录 `DDE_outputs/` 被上级目录 `.gitignore` 忽略，运行结果保留在本地，便于按需归档。

查看参数帮助：

```bash
python3 -X utf8 "/home/zhangpengyue/benchmark/cross-x/knowledge/verification/process_auditing/DDE/domain_distribution_entropy.py" --help
```

## 验证代码

```bash
python3 -X utf8 -m unittest discover \
  -s "/home/zhangpengyue/benchmark/cross-x/knowledge/verification/process_auditing/DDE/DDE_tests" -v
```

测试使用临时构造数据，不依赖真实语料。18 项测试涵盖：均匀和集中分布、手算非均匀熵、双/三/四域、相同边缘分布但不同组合熵、等权宏平均、重复记录、字段校验、缺失值与输出保护。
