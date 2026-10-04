# 需求查询向量

`embed_required_key_facts.py` 把步骤 2 每个新增领域的三个 `key_fact` 转为 `(domain, query)`，复用原版 Qwen 编码器、配置校验和向量缓存。完整步骤由 [run_3.sh](run_3.sh) 执行，包含语料编码、查询编码和检索：

```bash
bash knowledge/pipielines_v5/run_3.sh
```

`run_3.sh` 读取 `V5_ROOT/2_extract_required_key_facts` 下的 21 个 JSONL 文件，向 `EMBEDDING_ROOT` 写入查询向量；同一库也保存原始 test 问答的语料向量。默认路径和设备配置见[运行说明](run_serial.md)。重复 `(domain, query)` 会去重，已有兼容查询向量不会重复编码。

只调用 Python 适配器时需提供 `--kind queries`、`--input` 和 `--embedding-root`；该适配器不会生成语料向量。步骤 3 的检索阶段只读向量库，不加载编码模型。
