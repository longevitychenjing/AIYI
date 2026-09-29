# 易占

基于确定性六爻规则、可追溯资料检索和流式模型解读的文化研究 MVP。结果仅供文化研究与娱乐，请理性对待。

## 本地前置条件

- Python 3.11+
- Docker Desktop（用于 Qdrant）

## 启动

### 前端流程预览（一键）

双击 `start-preview.bat`。它会依次确认并启动 Ollama、预热 `qwen2.5:7b`、启动 API 和 `preview/three-step.html` 静态服务，最后自动打开三阶段交互预览。若服务已经运行，脚本会复用现有服务。

### 完整开发环境

1. 复制 `.env.example` 为 `.env`，需要真实模型时填写 OpenAI-compatible 的 chat 与 embedding 配置。
2. 启动向量库：`docker compose up -d`。
3. 安装 API：`py -m pip install -e packages/liuyao -e "apps/api[dev]"`。
4. 启动 API、Ollama 和 three-step 前端：双击 `start-preview.bat`。

保持 `YIJING_LLM_PROVIDER=local` 时，后端会以明确标识的开发说明文本演示 SSE 与引用，不会伪装为真实 AI 解读。配置 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL` 并将 provider 设为非 `local` 值后，才会调用 OpenAI-compatible 模型。

默认 `YIJING_RETRIEVER=sqlite` 会检索项目已有的本地知识库。导入向量后设为 `qdrant`，并填写 `EMBEDDING_*`，API 才会以语义向量召回带来源的资料；`qwen2.5:7b` 负责生成，不负责 embedding。

## 导入资料

检查 [资料约定](docs/sources.md)，确认文本可用后：

`py -m pip install -e packages/rag`

`yijing-ingest data/sources/manifest.json --fake-embeddings`

`--fake-embeddings` 仅用于本地链路验证。生产环境应配置 `EMBEDDING_BASE_URL`、`EMBEDDING_API_KEY` 与 `EMBEDDING_MODEL` 后使用真实向量。

### 导入固定卦辞和爻辞

本地 SQLite 可直接保存本卦、变卦和动爻所需的固定原文，不需要向量检索。已审核来源和复现信息见 [资料约定](docs/sources.md)。安装 API 包后执行：

`yijing-import-freizl-yijing`

该命令将固定版本的来源文件归档到 `data/sources/freizl-yijing/64gua.json`，并写入 64 条卦辞和 384 条爻辞及其出处哈希。

## 验证

`py -m pytest apps/api/tests -q`
