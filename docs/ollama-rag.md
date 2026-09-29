# Ollama 与 RAG 使用说明

## 1. 先验证本地模型

本项目使用 Ollama 原生流式接口。日常启动请直接双击仓库根目录的 `start-preview.bat`；脚本会启动服务、检查并预热 `qwen2.5:7b`，再启动 API 和 three-step 前端。手动检查时可运行：

```powershell
ollama list
ollama run qwen2.5:7b
```

`.env` 中至少设置：

```dotenv
YIJING_LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen2.5:7b
YIJING_RETRIEVER=sqlite
```

启动 API 后，完成六爻起卦即可看到真实模型的流式解读。结果页的“继续对话”会调用 `/api/v1/chat/stream`，并保留本轮消息上下文。

## 2. RAG 做了什么

流程是“确定性排盘 -> 检索 -> 把检索片段和出处放入提示词 -> 模型生成”。模型不负责计算本卦、变卦或动爻；它只解释后端已经算好的结果。每个检索片段都会带 `source_id`、标题、定位和内容哈希，前端会单独展示引用。

默认 `YIJING_RETRIEVER=sqlite` 会直接检索项目已有的 SQLite 知识库（当前包含 448 条卦辞、爻辞），不需要额外下载 embedding 模型。`sample` 才是只读样例资料的关键词检索模式。

要启用语义向量检索：

```dotenv
YIJING_RETRIEVER=qdrant
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=yijing_sources
EMBEDDING_BASE_URL=<OpenAI-compatible embedding endpoint>
EMBEDDING_API_KEY=<key>
EMBEDDING_MODEL=<embedding model>
```

然后执行：

```powershell
docker compose up -d
py -m pip install -e packages/rag
yijing-ingest data/sources/manifest.example.json --fake-embeddings
```

`--fake-embeddings` 只用于链路测试，不适合质量评估。Ollama 的 `qwen2.5:7b` 是生成模型，不是 embedding 模型；语义检索需要另装 embedding 模型，例如 `ollama pull nomic-embed-text`，并让导入脚本和 API 使用同一个 embedding 模型。第一阶段推荐先用 SQLite 模式验证资料召回和引用，再接入向量模型。

## 3. 这套 RAG 的工作边界

一次起卦的链路可以拆成四步：

1. 规则引擎计算本卦、变卦和动爻；这些结果不交给模型计算。
2. 检索器用问题、卦名和爻位召回少量经典文本。
3. API 把召回片段连同来源定位放进模型上下文。
4. Ollama 只负责根据固定卦象和资料生成解释，并通过 SSE 返回文字和引用。

RAG 提升的重点不是把模型改大，而是让召回内容正确、片段足够短、每条内容可追溯。建议比较同一个问题在 `sample`、`sqlite` 和 `qdrant` 三种模式下的引用，再调整模型提示词。

## 4. 常见问题

- Ollama 连接失败：检查 `OLLAMA_BASE_URL`，并确认 `ollama serve` 正在运行。
- 模型回答编造出处：检查检索是否为空；增加系统提示约束，并优先完善来源和分块，而不是只调高模型温度。
- 回答太长或上下文超限：减少召回数量，或把长文按章节和爻位切块；当前检索器默认最多返回 4 个片段。
