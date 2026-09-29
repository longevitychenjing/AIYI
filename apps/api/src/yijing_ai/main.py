from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from yijing_liuyao import LineValue, cast

from .knowledge import build_transition_reading, get_hexagram
from .rag import build_retriever
from .readings import stream_chat, stream_reading


class CastingRequest(BaseModel):
    lines: list[LineValue] = Field(min_length=6, max_length=6, description="Six lines from bottom to top")
    question: str = Field(min_length=1, max_length=500)
    cast_at: datetime | None = None


class HexagramResponse(BaseModel):
    name: str
    binary_key: str


class CastingResponse(BaseModel):
    lines: list[LineValue]
    original: HexagramResponse
    changed: HexagramResponse
    moving_line_positions: list[int]
    cast_at: datetime
    rule_version: str = "liuyao-mvp-1"


class ReadingRequest(CastingRequest):
    pass


class TransitionReadingRequest(BaseModel):
    lines: list[LineValue] = Field(min_length=6, max_length=6, description="Six lines from bottom to top")


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=12000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=40)

    @field_validator("messages")
    @classmethod
    def require_user_message(cls, value: list[ChatMessage]) -> list[ChatMessage]:
        if not any(message.role == "user" for message in value):
            raise ValueError("At least one user message is required.")
        return value


app = FastAPI(title="易占 API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:4173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:4173",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
retriever = build_retriever()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/knowledge/hexagrams/{binary_key}")
def get_knowledge_hexagram(binary_key: str) -> dict[str, object]:
    result = get_hexagram(binary_key)
    if result is None:
        raise HTTPException(status_code=404, detail="Unknown hexagram binary key.")
    return result


@app.post("/api/v1/knowledge/transition-readings")
def get_transition_reading(payload: TransitionReadingRequest) -> dict[str, object]:
    try:
        result = cast(payload.lines)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return build_transition_reading(result)


@app.post("/api/v1/castings", response_model=CastingResponse)
def create_casting(payload: CastingRequest) -> CastingResponse:
    try:
        result = cast(payload.lines)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    cast_at = payload.cast_at or datetime.now(ZoneInfo("Asia/Shanghai"))
    return CastingResponse(
        lines=list(result.lines),
        original=HexagramResponse(**result.original.__dict__),
        changed=HexagramResponse(**result.changed.__dict__),
        moving_line_positions=list(result.moving_line_positions),
        cast_at=cast_at,
    )


@app.post("/api/v1/readings/stream")
def create_reading_stream(payload: ReadingRequest) -> StreamingResponse:
    try:
        result = cast(payload.lines)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return StreamingResponse(
        stream_reading(payload.question, result, retriever),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/v1/chat/stream")
def create_chat_stream(payload: ChatRequest) -> StreamingResponse:
    return StreamingResponse(
        stream_chat([message.model_dump() for message in payload.messages], retriever),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
