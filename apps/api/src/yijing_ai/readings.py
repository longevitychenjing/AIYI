from collections.abc import Iterator, Sequence
import json
import os

import httpx
from yijing_liuyao import Casting

from .rag import KnowledgeChunk, Retriever


def _event(event: str, data: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


SYSTEM_PROMPT = (
    "你是六爻文化研究助手。只可依据给出的卦象、实际动爻和资料解释；"
    "不可自行计算卦象、虚构典籍出处或给出确定性预测。医疗、法律、财务等问题只能提示用户咨询专业人士。"
    "回答必须按三层展开：第一层‘本卦故事’，直接讲本卦卦名、卦辞、相关资料所呈现的象征场景、处境、人物关系或行动张力；这是卦象自身的叙事，不是现代案例，不要擅自编造现代人物、对白或情节。"
    "第二层‘变卦故事’，直接讲变卦可能呈现的象征场景、转折和发展方向；使用‘可能、像是、提示’等措辞，不把变卦说成确定的未来，只依据变卦卦辞或资料中明确提供的内容。"
    "第三层‘映射到用户问题’，在前两层之后，才把本卦故事和变卦故事映射到用户实际提出的问题，用隐喻说明相似处、张力和可观察的选择；明确这是文化性的象征解读，不是预言。"
    "不要写‘易经小故事式’现代转述，不要把卦象改写成当代职场、爱情或家庭短篇故事，不要把现代情节冒充经典故事。"
    "只解释实际发动的本卦爻位；变卦只解释变卦卦辞或资料中明确提供的内容，不要把本卦动爻误称为变卦的爻。若用户问题为空或只是占位说明，只讲本卦故事、变卦故事和需要用户补充的问题，不做个人映射。"
    "优先使用以下 Markdown 结构：‘### 本卦故事’、‘### 变卦故事’、‘### 映射到你的问题’、‘### 可以继续观察什么’，并用编号列表列出建议，不要输出连续的大段无结构文字。"
)


def _references(chunks: Sequence[KnowledgeChunk]) -> str:
    return "\n\n".join(
        f"[{chunk.citation.citation_id}] {chunk.citation.title}，{chunk.citation.locator}\n{chunk.content}"
        for chunk in chunks
    )


def _stream_ollama(messages: list[dict[str, str]]) -> Iterator[str]:
    base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL") or os.getenv("LLM_MODEL")
    if not model:
        raise ValueError("未配置 OLLAMA_MODEL（或 LLM_MODEL）。")
    with httpx.Client(timeout=120) as client:
        with client.stream(
            "POST",
            f"{base_url}/api/chat",
            json={"model": model, "messages": messages, "stream": True, "options": {"temperature": 0.3}},
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line:
                    continue
                payload = json.loads(line)
                content = payload.get("message", {}).get("content")
                if content:
                    yield content
                if payload.get("done"):
                    break


def _stream_openai_compatible(messages: list[dict[str, str]]) -> Iterator[str]:
    required = ("LLM_BASE_URL", "LLM_MODEL")
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise ValueError(f"OpenAI-compatible 模型配置不完整：{', '.join(missing)}。")
    base_url = os.environ["LLM_BASE_URL"].rstrip("/")
    headers = {}
    if os.getenv("LLM_API_KEY"):
        headers["Authorization"] = f"Bearer {os.environ['LLM_API_KEY']}"
    with httpx.Client(timeout=120) as client:
        with client.stream(
            "POST",
            f"{base_url}/chat/completions",
            headers=headers,
            json={"model": os.environ["LLM_MODEL"], "messages": messages, "stream": True, "temperature": 0.3},
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line.startswith("data: "):
                    continue
                data = line.removeprefix("data: ")
                if data == "[DONE]":
                    break
                token = json.loads(data)["choices"][0]["delta"].get("content")
                if token:
                    yield token


def _stream_model(messages: list[dict[str, str]]) -> Iterator[str]:
    provider_name = os.getenv("YIJING_LLM_PROVIDER", "local").lower()
    if provider_name == "ollama":
        yield from _stream_ollama(messages)
    elif provider_name in {"openai", "openai-compatible", "local-api"}:
        yield from _stream_openai_compatible(messages)
    else:
        yield "这是开发模式下的本地演示。配置 YIJING_LLM_PROVIDER=ollama 并填写模型后，才会调用真实模型。"


def stream_reading(question: str, casting: Casting, retriever: Retriever) -> Iterator[str]:
    query = f"{question} {casting.original.name} {casting.changed.name}"
    chunks = retriever.search(query)
    yield _event("meta", {"original": casting.original.name, "changed": casting.changed.name})

    provider_name = os.getenv("YIJING_LLM_PROVIDER", "local")
    evidence = "；".join(chunk.content for chunk in chunks)
    if provider_name == "local":
        text = (
            f"这是开发模式下的资料检索演示。本次起得“{casting.original.name}”"
            f"，变为“{casting.changed.name}”。"
            f"动爻在第 {', '.join(map(str, casting.moving_line_positions)) or '无'} 爻。"
            "以下内容仅作文化研究与娱乐参考，不构成决策依据。"
        )
        text += f" 检索到的相关资料提示：{evidence}" if evidence else " 当前资料库没有召回直接相关的断语，因此不作延伸判断。"
        for token in text:
            yield _event("token", {"text": token})
    else:
        references = _references(chunks)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"占问：{question}\n本卦：{casting.original.name}\n变卦：{casting.changed.name}\n动爻：{list(casting.moving_line_positions)}\n\n资料：\n{references or '未检索到资料'}",
            },
        ]
        try:
            for token in _stream_model(messages):
                yield _event("token", {"text": token})
        except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            yield _event("error", {"message": "模型请求失败，未生成解读。", "detail": str(error)})
            return
    for chunk in chunks:
        citation = chunk.citation
        yield _event(
            "citation",
            {
                "citation_id": citation.citation_id,
                "source_id": citation.source_id,
                "title": citation.title,
                "locator": citation.locator,
                "source_url": citation.source_url,
            },
        )
    yield _event("done", {"provider": provider_name, "citation_count": len(chunks)})


def stream_chat(messages: Sequence[dict[str, str]], retriever: Retriever) -> Iterator[str]:
    """Stream a follow-up conversation, grounding the latest user turn in retrieved sources."""
    user_messages = [message for message in messages if message.get("role") == "user"]
    retrieval_query = "\n".join(message["content"] for message in messages[-8:] if message.get("role") == "user")
    chunks = retriever.search(retrieval_query) if retrieval_query else []
    grounded = [
        {"role": "system", "content": SYSTEM_PROMPT + "如果资料不足，请明确说资料不足，不要补写不存在的原文。"},
        *messages,
    ]
    if chunks:
        grounded.insert(
            1,
            {"role": "system", "content": f"本轮可参考资料：\n{_references(chunks)}"},
        )
    yield _event("meta", {"citation_count": len(chunks)})
    try:
        for token in _stream_model(grounded):
            yield _event("token", {"text": token})
    except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        yield _event("error", {"message": "模型请求失败。", "detail": str(error)})
        return
    for chunk in chunks:
        citation = chunk.citation
        yield _event(
            "citation",
            {
                "citation_id": citation.citation_id,
                "source_id": citation.source_id,
                "title": citation.title,
                "locator": citation.locator,
                "source_url": citation.source_url,
            },
        )
    yield _event("done", {"provider": os.getenv("YIJING_LLM_PROVIDER", "local"), "citation_count": len(chunks)})
