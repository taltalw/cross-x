# Pipelines v2

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

包装脚本默认处理每个领域前 10 个样本，结果写入
`knowledge/pipelines_v2/outputs/0_extract_key_facts/<domain>/test.jsonl`。
可以用 `NUM=20` 修改每个领域的样本数，用 `ATOMIC_SPLIT=train` 切换数据集；
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
