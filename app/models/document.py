from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class DocumentBase(BaseModel):
    title: str
    description: Optional[str] = None
    tags: Optional[str] = None
    uploader: Optional[str] = "System"
    chat_source: Optional[str] = "Direct Upload"


class DocumentCreate(DocumentBase):
    filename: str
    gdrive_file_id: str
    gdrive_link: str
    file_type: Optional[str] = None
    file_size: Optional[int] = 0


class WhatsAppMediaPayload(BaseModel):
    """Payload from WhatsApp bot containing media metadata for server-side CDN download & decryption."""
    directPath: Optional[str] = None
    url: Optional[str] = None
    mediaKey: str
    mimetype: str = "application/pdf"
    mediaType: str = "document"
    filename: Optional[str] = None
    title: Optional[str] = None
    uploader: Optional[str] = "WhatsApp User"
    chat_source: Optional[str] = "WhatsApp Chat"
    description: Optional[str] = None
    tags: Optional[str] = None


class LinkPayload(BaseModel):
    """Payload for registering a shared document link (Google Docs/Sheets/Drive URL) without uploading a file."""
    url: str
    title: Optional[str] = None
    uploader: Optional[str] = "WhatsApp User"
    chat_source: Optional[str] = "WhatsApp Chat"
    description: Optional[str] = None
    tags: Optional[str] = None



class DocumentResponse(BaseModel):
    id: str
    title: str
    filename: str
    gdrive_file_id: str
    gdrive_link: str
    file_type: Optional[str] = None
    file_size: Optional[int] = 0
    uploader: Optional[str] = None
    chat_source: Optional[str] = None
    tags: Optional[str] = None
    description: Optional[str] = None
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class DocumentSearchResult(BaseModel):
    id: str
    title: str
    gdrive_link: str
    file_type: Optional[str] = None
    file_size: Optional[int] = 0
    uploader: Optional[str] = None
    chat_source: Optional[str] = None
    tags: Optional[str] = None
    description: Optional[str] = None
    score: Optional[float] = 0.0
    created_at: Optional[str] = None


class SearchResponse(BaseModel):
    query: str
    total: int
    page: int
    size: int
    results: List[DocumentSearchResult]


class UploadResponse(BaseModel):
    success: bool
    message: str
    document: Optional[DocumentResponse] = None
