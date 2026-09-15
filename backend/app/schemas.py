"""Pydantic 请求/响应模型"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------- 知识库 ----------
class KBCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = ""
    domains: list[str] = []


class KBUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    description: Optional[str] = None
    domains: Optional[list[str]] = None


class KBOut(BaseModel):
    id: int
    name: str
    description: str
    domains: list[str]
    doc_count: int = 0
    chunk_count: int = 0
    char_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------- 文档 ----------
class DocumentOut(BaseModel):
    id: int
    kb_id: int
    title: str
    filename: str
    file_type: str
    file_size: int
    char_count: int
    chunk_count: int
    status: str
    error_msg: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------- 会话/消息 ----------
class SessionCreate(BaseModel):
    kb_id: int
    title: str = "新会话"


class SessionOut(BaseModel):
    id: int
    kb_id: int
    title: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ReferenceItem(BaseModel):
    chunk_id: int
    doc_id: int
    doc_title: str
    seq: int
    score: float


class MessageOut(BaseModel):
    id: int
    session_id: int
    role: str
    content: str
    references: list[Any] = []
    answer_type: str = ""
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatRequest(BaseModel):
    session_id: int
    question: str = Field(min_length=1, max_length=2000)


# ---------- 统计 ----------
class StatsOverview(BaseModel):
    kb_count: int
    doc_count: int
    chunk_count: int
    question_count: int
    hit_rate: float
    avg_score: float


# ---------- RAG 评测 ----------
class EvalQuestionCreate(BaseModel):
    kb_id: int
    question: str = Field(min_length=1, max_length=2000)
    ground_truth_doc_ids: list[int] = []
    ground_truth_chunk_ids: list[int] = []
    note: str = ""


class EvalQuestionOut(BaseModel):
    id: int
    kb_id: int
    question: str
    ground_truth_doc_ids: list[int]
    ground_truth_chunk_ids: list[int]
    note: str
    created_at: datetime

    model_config = {"from_attributes": True}


class EvalQuestionUpdate(BaseModel):
    question: Optional[str] = None
    ground_truth_doc_ids: Optional[list[int]] = None
    ground_truth_chunk_ids: Optional[list[int]] = None
    note: Optional[str] = None


class EvalRunRequest(BaseModel):
    kb_id: int
    question_ids: list[int] = Field(default_factory=list)


class EvalRunOut(BaseModel):
    id: int
    kb_id: int
    question_ids: list[int]
    items: list[Any] = []
    summary: dict = {}
    status: str
    error_msg: str
    elapsed_s: float
    created_at: datetime

    model_config = {"from_attributes": True}
