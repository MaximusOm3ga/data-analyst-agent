from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime

class Attachment(BaseModel):
    filename: str
    url: Optional[str]
    mime_type: Optional[str]

class CommonTicket(BaseModel):
    ticket_id_source: str
    source_channel: str
    requester_identifier: str
    subject: Optional[str]
    body_raw: str
    body_cleaned: Optional[str]
    attachments: List[Attachment] = []
    timestamp_received: datetime
    channel_metadata: Dict[str, Any] = {}

class EnrichmentContext(BaseModel):
    requester_context: Dict[str, Any] = {}
    asset_context: Dict[str, Any] = {}
    history_context: Dict[str, Any] = {}

class ClassificationOutput(BaseModel):
    category: str
    subcategory: Optional[str]
    priority: str
    queue: str
    confidence: float
    summary: str
    extracted_entities: Dict[str, List[str]] = {}
    urgency_flags: List[str] = []
    suggested_kb_article_ids: List[str] = []
    recommended_action: str
    reasoning: Optional[str]

class KnowledgeBaseDocument(BaseModel):
    id: str
    title: str
    content: str
    source_url: Optional[str] = None
    category: Optional[str] = None
    metadata: Dict[str, Any] = {}

class KnowledgeBaseIngestRequest(BaseModel):
    documents: List[KnowledgeBaseDocument]

class KnowledgeBaseSearchResult(BaseModel):
    id: str
    text: str
    score: float
    metadata: Dict[str, Any] = {}
