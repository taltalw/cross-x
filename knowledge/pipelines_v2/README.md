# Pipelines v2

推荐使用三个统一串行入口（配置集中在 [run_config.sh](run_config.sh)）：

```bash
bash knowledge/pipelines_v2/run_012.sh && \
bash knowledge/pipelines_v2/run_embedding_retrieve.sh && \
bash knowledge/pipelines_v2/run_4.sh
```

步骤 0 标注七领域的全部 test；步骤 1 按七源领域 × 总领域数 2、3、4 生成思路（每组默认 10 个样本，可设 `NUM=all`），步骤 2、检索和步骤 4 消费全部上一步结果。详见 [三段入口说明](run_serial.md)。

## 0. Extract key facts

`0_extract_key_facts.py` 读取 atomic samples（JSONL，每行包含 `prompt` 和
`completion`），让 LLM 回答 **What is this sample about?**，用 2–3 个简短的
英文关键词组概括样本核心知识，输出为 `key_facts`。

在 `cross-x` 目录运行（沿用原 pipeline 的 API 环境变量）：

```bash
export API_BASE_URL=https://your-provider/v1
export API_KEY=your-key
export MODEL=your-model

python knowledge/pipelines_v2/0_extract_key_facts.py \
  --input knowledge/atomic/computer_science/test.jsonl \
  --num 10
```

也可以用包装脚本一次处理所有领域的 `test.jsonl`：

```bash
export API_BASE_URL=https://your-provider/v1
export API_KEY=your-key
export MODEL=your-model
bash knowledge/pipelines_v2/run_0_extract_key_facts.sh
```

单步步骤 0 包装脚本默认处理每个领域全部样本，结果写入
`knowledge/pipelines_v2/outputs/0_extract_key_facts/<domain>/test.jsonl`。
单步试跑可用 `KEY_FACT_NUM=20` 限制条数，用 `ATOMIC_SPLIT=train` 切换数据集；统一入口固定处理完整 test。
额外参数会传给 Python 脚本，
例如 `bash knowledge/pipelines_v2/run_0_extract_key_facts.sh --overwrite`。

省略 `--num` 处理全部样本。领域默认从已知 atomic 领域目录推断，也可通过
`--source-domain` 指定；任意其他目录的输入也可以直接使用。
默认输出到 `knowledge/pipelines_v2/outputs/0_extract_key_facts/<domain>/<input filename>`，
未知领域使用 `unknown`。可用 `--output` 指定路径。

输出示例（每行一个 JSON 对象）：

```json
{"source_file":"/path/to/test.jsonl","source_line":1,"sample":{"prompt":"The length of the IPv4 packet header is variable. True or False?","completion":"True"},"key_facts":["IPv4 packet header","variable header length"],"model":"your-model","source_domain":"computer_science"}
```

原样本所有字段均保留；只将题目和答案发送给 LLM。程序校验关键词组数量、非空和
重复项；词组是否准确、简短由提示词约束，仍需抽查真实模型输出。
临时请求错误或不合规输出默认重试 2 次（`--retries`）；失败时停止并保留已完成行。
已有输出需显式 `--overwrite` 才会从头覆盖。

离线测试：

```bash
python -m unittest discover -s knowledge/pipelines_v2/tests -v
```

后续流程：第 1 步由模型选择融合领域并给出简洁构造思路 → 第 2 步为每个所选领域提取 3 个 required key facts → 预计算这些需求的 query 向量 → 第 3 步 BM25 + 语义向量检索 → 第 4 步结合各领域样本、key facts 和构造思路生成问题。

第 1 步只需 `--domain-count N`，包含源领域。例如 N=3，模型从其他六个领域中选择两个。第 2–4 步直接读取每条记录的 `fusion_domains`，不再接受 `--fusion-domains`。四类答案构造思路和最终四选项不随领域数变化。

单步 `.sh` 用 `SOURCE_DOMAIN` 选择源领域，`DOMAIN_COUNT` 设置总数。1–4 步的路径含领域数量：`<source>/<split>_domain_count_<N>.jsonl`，避免不同数量的结果相互覆盖。API 设置沿用环境变量或脚本顶部配置。

使用说明：[步骤 1](1_generate_fusion_plans.md)、[步骤 2](2_extract_required_key_facts.md)、[向量准备](embed_required_key_facts.md)、[步骤 3](3_retrieve_key_fact_matches.md)、[步骤 4](4_generate_fusion_question.md)。步骤 3 需要向量库和检索语料对应的步骤 0 标注，统一入口会准备这些数据；单步脚本需要自行准备。

## 中英文模板 / Bilingual Templates

- [0_extract_key_facts 中英文模板](0_extract_key_facts_prompt_bilingual.md)
- [1_generate_fusion_plans 中英文模板](1_generate_fusion_plans_prompt_bilingual.md)
- [2_extract_required_key_facts 中英文模板](2_extract_required_key_facts_prompt_bilingual.md)
- [3_retrieve_key_fact_matches 中英文模板](3_retrieve_key_fact_matches_template_bilingual.md)
- [4_generate_fusion_question 中英文模板](4_generate_fusion_question_prompt_bilingual.md)
