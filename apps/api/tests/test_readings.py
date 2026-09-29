from pathlib import Path

from yijing_ai import readings
from yijing_ai.rag import Citation, KnowledgeChunk, SQLiteRetriever


def test_sqlite_retriever_returns_the_requested_hexagram_text() -> None:
    database_path = Path(__file__).resolve().parents[3] / "data" / "knowledge" / "yijing.db"
    retriever = SQLiteRetriever(database_path)

    chunks = retriever.search("水雷屯 起始阶段", limit=4)

    assert chunks
    assert all("水雷屯" in chunk.citation.title for chunk in chunks)
    assert any("屯" in chunk.content for chunk in chunks)


class RecordingRetriever:
    def __init__(self) -> None:
        self.query = ""

    def search(self, query: str, limit: int = 4) -> list[KnowledgeChunk]:
        self.query = query
        return [
            KnowledgeChunk(
                citation=Citation("source-1", "book-1", "周易样例", "第 1 段", "https://example.test/source"),
                content="样例资料内容",
            )
        ]


def test_follow_up_chat_retrieves_using_recent_user_context(monkeypatch) -> None:
    retriever = RecordingRetriever()
    captured: list[dict[str, str]] = []

    def fake_stream_model(messages: list[dict[str, str]]):
        captured.extend(messages)
        yield "参考资料后的回答"

    monkeypatch.setattr(readings, "_stream_model", fake_stream_model)
    events = list(
        readings.stream_chat(
            [
                {"role": "user", "content": "近期工作方向怎么取舍？本卦水火未济"},
                {"role": "assistant", "content": "先检查尚未完成的准备。"},
                {"role": "user", "content": "请结合第 3 爻再说明"},
            ],
            retriever,
        )
    )

    assert retriever.query == "近期工作方向怎么取舍？本卦水火未济\n请结合第 3 爻再说明"
    assert any("样例资料内容" in message["content"] for message in captured)
    assert "本卦故事" in captured[0]["content"]
    assert "变卦故事" in captured[0]["content"]
    assert "映射到你的问题" in captured[0]["content"]
    assert any('event: token\ndata: {"text": "参考资料后的回答"}' in event for event in events)
    assert any('event: citation\ndata:' in event for event in events)
    assert any('event: done\ndata:' in event for event in events)
