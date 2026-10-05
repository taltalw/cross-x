# CDNS Prompt 领域遮蔽评测

Python 3.10+，仅标准库。当前完成实现和离线验证，未运行真实模型实验。

指标详解：[CDNS 定义与实现说明](../design_docs/CDNS_跨域必要性_指标定义与实现说明_20261005.md)。

## 一键准备与预览（不调用模型）

```bash
cd "/home/zhangpengyue/benchmark/cross-x/knowledge/verification/process_auditing/CDNS"
bash "CDNS_run_example.sh" prepare
bash "CDNS_run_example.sh" dry-run
```

默认从真实阶段 4 数据中，每个源域×k 取第一条 easy，共 21 题、168 请求，输出到 `CDNS_outputs/CDNS_example/`。准备和 dry-run 完全离线；dry-run 不创建预测文件、不读取密钥。

所有写入拒绝覆盖已有成果。再次执行准备需改目录：

```bash
bash "CDNS_run_example.sh" prepare --output-dir "CDNS_outputs/CDNS_example_v2"
bash "CDNS_run_example.sh" dry-run --input-dir "CDNS_outputs/CDNS_example_v2"
```

指定完整参数、全部难度和全部样本（仅生成输入，未来完整推理需 50,070 请求）：

```bash
python3 -X utf8 "CDNS_prepare.py" \
  --input "../../../pipielines_v4/outputs/4_generate_fusion_question" \
  --output-dir "CDNS_outputs/CDNS_all"
```

`--materials-source retrieved` 默认新增域全部检索材料；`--materials-source used` 使用生成时实际采用材料；源域均来自 `sample`。原生 `knowledge.<domain>.materials[]` 直接使用已有材料，忽略材料来源开关。`--difficulty` 可选 easy/medium/hard；`--per-group N` 按源域×k×难度确定性取前 N 条。

当前自动评分只支持 `options` 对象形式的单选题，答案为对应标签；开放问答不自动判分。

## 准备输出

| 文件 | 内容 |
|---|---|
| `CDNS_samples.jsonl` | 规范 question/options/knowledge、分组字段与来源；无金标 |
| `CDNS_answers.jsonl` | sample_id、标准答案，仅用于评分 |
| `CDNS_requests.jsonl` | Full/Mask/No Domain/Only 的 messages 和条件身份 |
| `CDNS_manifest.json` | 输入路径、SHA256、材料模式、样本与条件数量、输出摘要 |

2/3/4 域分别生成 6/8/10 条请求，源领域也参与 Mask 和 Only。模型可见部分不包含融合问题金标、解析、计划或干扰项分析。参考原子材料的 prompt/completion 保留并标记为参考问答，不把其所有选项都当作事实。

每个条件作答一次，暂不支持重复采样；重复 request_id 会被评分拒绝。

## 将来运行推理（本轮未执行）

接口契约：向指定 endpoint POST JSON `model/messages/temperature/max_tokens`（可选 seed），响应提供 `choices[0].message.content` 和 `choices[0].finish_reason`。适用于提供该聊天 JSON 协议的本地或远程推理服务，不自动安装模型或启动服务。

只有加 `--execute` 才发送真实请求。以下 MODEL_NAME、端口需替换为实际服务配置：

```bash
python3 -X utf8 "CDNS_infer.py" \
  --input-dir "CDNS_outputs/CDNS_example" \
  --output "CDNS_outputs/CDNS_predictions.jsonl" \
  --endpoint "http://127.0.0.1:8000/v1/chat/completions" \
  --model "MODEL_NAME" --temperature 0 --max-tokens 256 \
  --execute
```

脚本等价入口：`bash CDNS_run_example.sh infer` 后附上 output/endpoint/model/execute 参数。若需鉴权，调用前在环境中设置 `CDNS_API_KEY`，也可通过 `--api-key-env` 指定现有环境变量名。密钥不写入文件。`--timeout` 默认 120 秒，可选 `--seed`；服务不支持某参数时应修正配置重跑，不静默移除。

实际调用只发送 messages 与推理参数，金标不发送。每条输出立即落盘，状态分为 `ok`、`invalid_format`、`error`。仅 finish_reason=`stop` 视为正常完成；截断和其他未完成终止视为 error。正确标签和 ABSTAIN 支持裸文本或 JSON answer；解释性长文本不会被程序猜测为某个选项。

不自动截断材料、不自动重试、不断点混拼不同运行。输出文件独占创建；中断后部分结果可以评分并报告缺失，重新推理使用新文件。服务后台权重版本需实验者固定，单靠相同模型名不能保证权重未变。

## 离线评分

```bash
python3 -X utf8 "CDNS_score.py" \
  --input-dir "CDNS_outputs/CDNS_example" \
  --predictions-file "CDNS_outputs/CDNS_predictions.jsonl" \
  --output-dir "CDNS_outputs/CDNS_scores"
```

- CDNS：完整样本中 Full 对且所有 Mask 错的比例，包括 Full 错的完整样本作为分母。
- DC：每个领域在相同 Full/Mask 配对样本上的准确率差，保留负值。
- IG：逐样本 Full 减最好的单域 Mask，再平均，保留负值。
- No Domain/Only：单独输出有效准确率和分母。
- ABSTAIN 为不正确；服务失败、格式错误、缺失不视为答错，排除并报告。
- 零分母输出 null，不是 0。缺失需关注选择偏差。
- 分组：overall、k、difficulty、source_domain、k×difficulty；组内样本等权，不是源域等权。

输出 `CDNS_metrics.json`、两份逐样本 JSONL、`CDNS_summary.csv`、`CDNS_DC.csv`、`CDNS_condition_accuracy.csv`、`CDNS_report.md`。

外部推理结果也可按以下格式导入，每条对应一个已有请求：

```json
{
  "request_id": "从 CDNS_requests.jsonl 复制",
  "prompt_sha256": "从同一请求复制",
  "inference_config": {"model": "固定模型及版本", "temperature": 0},
  "inference_id": "CDNS_data.digest(inference_config) 的结果",
  "simulation": false,
  "status": "ok",
  "answer": "A"
}
```

所有结果必须使用相同 inference_config；不得混合模拟与真实结果。错误记录不需 answer；status 为 error 或 invalid_format。原文件摘要校验失败时重新准备，不能手改请求后仍沿用旧预测。

## 离线验证（可运行）

```bash
bash "CDNS_run_example.sh" test
bash "CDNS_run_example.sh" validate --output-dir "CDNS_outputs/CDNS_validation_again"
```

验证器对真实输入全量读取审计，再为 21 题生成 168 条请求，用人为设定的模拟回答跑完评分；网络入口被 mock 禁止访问。结果中的 `simulation: true` 始终保留，模拟分数不是真实质量分数。

已完成：22 项测试；真实 6,255 题的两种材料适配及源文件哈希检查；21 题 168 请求的模拟端到端验证；独立审查 351 种结果组合；Python/Shell 语法检查。真实模型调用为 0。

当前验证报告：[CDNS_validation.json](CDNS_outputs/CDNS_validation/CDNS_validation.json)。
