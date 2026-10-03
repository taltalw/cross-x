# Pipelines v4

在 `cross-x` 目录，一次性安装与现有 `crossx` 环境对应的 v4 依赖：

```bash
bash knowledge/pipielines_v4/install_env.sh
```

安装到 `knowledge/pipielines_v4/.env`，不修改现有 `crossx` 环境。依赖版本见 [requirements-crossx.txt](requirements-crossx.txt)。本机已有 `crossx` 环境时可以跳过安装；启动脚本会优先使用本地 `.env`，否则使用本机 `crossx` 环境。

只需配置 API 信息，再使用已有步骤 0、1结果重跑步骤 2、3、4：

```bash
export API_BASE_URL=https://your-provider/v1
export API_KEY=your-key
export MODEL=your-model
bash knowledge/pipielines_v4/run_all.sh
```

共享配置见 [run_config.sh](run_config.sh)。默认处理七领域的 `test.jsonl`；步骤 1 对每个源领域及总领域数 2、3、4 各取前 100 条，可用 `NUM=all` 处理全部。`NUM` 不限制步骤 0；步骤 2–4 消费上一步的全部结果。步骤 3 每个新增领域最多保留 10 条候选。输出默认写入 `knowledge/pipielines_v4/outputs`，向量库默认位于 `knowledge/embeddings/v4-test-Qwen3-Embedding-8B`。步骤 3 自动选择 CUDA 或 CPU；没有可用 NVIDIA 驱动时会用 CPU，编码速度会明显较慢。

| 步骤 | 单独入口 | 工作 |
| --- | --- | --- |
| 0 | [run_0.sh](run_0.sh) | 为全部原子问答提取 key facts |
| 1 | [run_1.sh](run_1.sh) | 选择融合领域并构造问题、答案思路 |
| 2 | [run_2.sh](run_2.sh) | 提取各新增领域的检索需求 |
| 3 | [run_3.sh](run_3.sh) | 编码语料和需求查询，执行混合检索 |
| 4 | [run_4.sh](run_4.sh) | 从候选样本构造并调整可行 plan，为其生成三种难度的问题 |

`run_all.sh` 要求步骤 0、1的输入结果已经存在，只执行步骤 2、3、4；步骤 0、1不会被重新调用。也可以单独运行五个入口。入口只接受可选的 `--overwrite`，会从头覆盖相应阶段的 JSONL；已有输出默认受保护。步骤 3 的向量缓存独立于 JSONL 覆盖参数。单步 Python 命令可使用各自的 `--input`、`--output` 和其他参数。

详细路径、配置与失败行为见[运行说明](run_serial.md)。提示词分别见[步骤 0](0_extract_key_facts_prompt_bilingual.md)、[步骤 1](1_generate_fusion_plans_prompt_bilingual.md)、[步骤 2](2_extract_required_key_facts_prompt_bilingual.md)和[步骤 4](4_generate_fusion_question_prompt_bilingual.md)。

离线测试：

```bash
python3 -m unittest discover -s knowledge/pipielines_v4/tests -v
```
