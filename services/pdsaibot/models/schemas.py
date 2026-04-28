"""Pydantic schemas for the hybrid PDSAI-Bot."""
from __future__ import annotations
from typing import Any, Optional
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    user_id: str = Field(default="anonymous")
    session_id: Optional[str] = None        # for multi-turn memory
    role: str = Field(default="citizen")    # admin | field_staff | citizen
    message: str
    language: str = Field(default="English")


class ChatResponse(BaseModel):
    module: str = "PDSAIBot"
    session_id: str
    user_id: str
    role: str
    message: str
    response: str
    intent: str
    intent_confidence: float
    source: str          # "rasa_nlu" | "langchain" | "rule_based"
    data: dict[str, Any] = {}
    insights: list[str] = []
    suggestions: list[str] = []
    language: str = "English"


class NLUResult(BaseModel):
    intent: str
    confidence: float
    entities: dict[str, Any] = {}
    source: str = "embedded"


class GrievanceRequest(BaseModel):
    user_id: str
    role: str = "citizen"
    location: Optional[str] = None
    fps_id: Optional[str] = None
    category: str = Field(default="general")
    description: str
    language: str = "English"


class GrievanceResponse(BaseModel):
    module: str = "PDSAIBot"
    ticket_id: str
    status: str
    message: str
    estimated_resolution_hours: int = 48
