# Embedding 环境与运行

本机是 Ubuntu x86_64、glibc 2.35、NVIDIA A800 80GB、驱动 570.86.15，驱动支持 CUDA 12.8。推荐下面这组版本：

| 组件 | 版本 |
| --- | --- |
| Python | 3.11 |
| PyTorch | 2.7.1，CUDA 12.8 wheel |
| Transformers | 4.51.3 |
| NumPy | 1.26.4 |
| safetensors | 0.5.3 |

PyTorch 官方提供该 CUDA 构建；Qwen3-Embedding 要求 Transformers 至少 4.51.0。使用预编译 wheel，无需为本脚本另装 CUDA Toolkit、FlashAttention、Sentence Transformers 或 FAISS。

参考：[PyTorch 官方安装版本](https://pytorch.org/get-started/previous-versions/)、[Qwen3-Embedding-8B 官方说明](https://huggingface.co/Qwen/Qwen3-Embedding-8B)。

## 安装

在独立 conda 环境安装，避免修改现有训练环境。直接执行安装命令，不使用 requirements 文件：

```bash
conda create -n crossx-embedding python=3.11 -y
conda activate crossx-embedding

python -m pip install torch==2.7.1 --index-url https://download.pytorch.org/whl/cu128
python -m pip install transformers==4.51.3 numpy==1.26.4 safetensors==0.5.3

python -c "import torch, transformers; print(torch.__version__, transformers.__version__); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0))"
```

## 在 Shell 中指定模型

直接修改 `run_embed_knowledge.sh` 顶部：

```bash
MODEL_NAME="Qwen/Qwen3-Embedding-8B"
GPU_ID="0"
DTYPE="bfloat16"
BATCH_SIZE=8
MAX_LENGTH=2048
CHUNK_OVERLAP=128
```

无需在终端 export 模型名、GPU 或 batch size。脚本通过 `--model` 把模型名称传给 Python；Python 使用 `AutoTokenizer.from_pretrained()` 和 `AutoModel.from_pretrained()` 在线下载并加载。首次运行需要访问 Hugging Face，后续复用本地下载缓存。

`GPU_ID` 指物理卡号；脚本为子进程设置可见设备，Python 使用进程内的 `cuda:0`，因此不会使用另一张卡。

模型名同时决定向量目录：`knowledge/embeddings/<模型名最后一段>/`。当前为 `knowledge/embeddings/Qwen3-Embedding-8B/`。

## 运行

```bash
conda activate crossx-embedding
cd /mnt/data1/wangyatong/cross-x

bash knowledge/pipelines/run_embed_knowledge.sh
```

依次生成：

1. `knowledge/atomic/<领域>/train.jsonl` 的语料向量，七个领域共用一套索引。
2. `knowledge/results_5.5/2_generate_knowledge_queries/` 与 `knowledge/results_6/2_generate_knowledge_queries/` 的 query 向量。

两组 query 使用相同的 embedding 模型与参数。默认运行无需 embedding API、API Key 或模型名环境变量。

## 指定其他数据路径

单独对某个文件生成向量：

```bash
python knowledge/pipelines/embed_knowledge.py \
  --kind corpus --input knowledge/atomic/medical/train.jsonl \
  --model Qwen/Qwen3-Embedding-8B --device cuda:0 --dtype bfloat16 \
  --embedding-root knowledge/embeddings/Qwen3-Embedding-8B
```

`--input` 支持多个 JSONL 文件、单领域目录或整个 `atomic` 目录。默认从文件父目录推断领域；文件放在其他位置时用 `--domain medical`。目录输入默认读取 train，可用 `--splits train dev` 更改范围。

只补充新 query：

```bash
python knowledge/pipelines/embed_knowledge.py \
  --kind queries --input /path/to/query.jsonl \
  --embedding-root knowledge/embeddings/Qwen3-Embedding-8B --device cuda:0
```

已有向量库的模型、revision、dtype、分块和 query 指令会被继承。需要完全离线加载已经下载的模型时，Python 入口支持 `--local-files-only`；默认不启用。

## 输出和复用

```text
knowledge/embeddings/Qwen3-Embedding-8B/
├── metadata.json      模型及编码配置
└── vectors.sqlite3    语料/query向量、原始问答、来源和分块映射
```

- 采用最后有效 token 池化、L2 归一化及完整 4096 维输出。
- 语料使用 `prompt + 换行 + completion`；按 token 分块，默认每块 2048 tokens、重叠 128 tokens，长文本不会丢掉尾部答案。
- Query 使用官方的 `Instruct: ...\nQuery:...` 格式，语料不加 query 指令；query 过长时明确报错，不静默截断。
- SQLite 按批次保存向量；相同命令重跑可复用已完成的编码。完整 corpus 成功后才原子发布。
- 语料来源或内容改变时，使用 `--replace-corpus` 显式重建。该参数不会强制重算仍可复用的向量。
- 模型、指令、dtype 或分块配置改变时，请使用新的向量目录；脚本会拒绝混用不同配置。
- 换模型时修改 Shell 的 `MODEL_NAME`，输出目录随之变化；同时修改检索 Shell 的 `EMBEDDING_ROOT` 指向新目录。

## 再运行检索

```bash
bash knowledge/pipelines/run_3_retrieve_knowledge.sh
```

默认读取 `knowledge/embeddings/Qwen3-Embedding-8B/`，不加载模型、不调用 API。BM25 和向量检索使用同一套保存的原始问答。缺少某个领域或 query 的向量时，会提示先运行 embedding。

输出分别位于 `knowledge/results_5.5/3_retrieve_knowledge/` 和 `knowledge/results_6/3_retrieve_knowledge/`。已有结果默认禁止覆盖；添加 `--overwrite` 可重跑。

检索只读取已生成的本地向量，不再提供 embedding API、模型名或在线编码参数。`METHOD=bm25` 可单独运行关键词检索。
