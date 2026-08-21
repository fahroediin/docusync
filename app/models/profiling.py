from pydantic import BaseModel
from typing import Optional, List


class PDFFileItem(BaseModel):
    """File item from GDrive folder listing for !daftar-pdf."""
    gdrive_file_id: str
    filename: str
    company_name: Optional[str] = None
    doc_date: Optional[str] = None
    size_bytes: int = 0
    size_mb: str = "0.00"
    created_time: Optional[str] = None
    web_view_link: Optional[str] = None


class PDFFileListResponse(BaseModel):
    """Response for listing all PDFs in the summary folder."""
    folder_id: str
    folder_name: Optional[str] = "Google Drive"
    total_files: int
    files: List[PDFFileItem]


class CompanyProfile(BaseModel):
    """Company profile metadata synced from Google Spreadsheet."""
    id: str
    company_name: str
    doc_date: Optional[str] = None
    category: Optional[str] = None
    summary: Optional[str] = None
    pic: Optional[str] = None
    gdrive_link: Optional[str] = None
    extra_info: Optional[str] = None
    synced_at: Optional[str] = None

    class Config:
        from_attributes = True


class CompanyProfileListResponse(BaseModel):
    """List of company profiles matching a query."""
    total: int
    profiles: List[CompanyProfile]


class SyncSheetResponse(BaseModel):
    """Response after syncing data from Google Spreadsheet."""
    success: bool
    message: str
    synced_count: int
