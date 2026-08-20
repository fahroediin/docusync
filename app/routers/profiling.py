import os
import re
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, status

from app.config import settings
from app.models.profiling import (
    PDFFileItem,
    PDFFileListResponse,
    CompanyProfile,
    CompanyProfileListResponse,
    SyncSheetResponse,
)
from app.services.gdrive_service import gdrive_service
from app.services.sheets_service import sheets_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/profiling", tags=["Profiling & PDF Catalog"])


def _parse_filename(filename: str) -> tuple[Optional[str], Optional[str]]:
    """
    Parse standardized filename: "Nama Perusahaan_DD-Bulan-YYYY.pdf"
    Returns: (company_name, doc_date)
    """
    clean_name = os.path.splitext(filename)[0]
    if "_" in clean_name:
        parts = clean_name.split("_", 1)
        return parts[0].strip(), parts[1].strip()
    return clean_name.strip(), None


@router.get("/pdfs", response_model=PDFFileListResponse, summary="Daftar file PDF di folder GDrive")
async def list_pdf_files():
    """
    Menampilkan daftar seluruh file PDF yang ada di folder Google Drive
    yang dikonfigurasi di GDRIVE_SUMMARY_FOLDER_ID (untuk !daftar-pdf).
    """
    folder_id = settings.GDRIVE_SUMMARY_FOLDER_ID
    if not folder_id:
        raise HTTPException(
            status_code=500,
            detail="GDRIVE_SUMMARY_FOLDER_ID belum dikonfigurasi di file .env."
        )

    try:
        files = await gdrive_service.list_folder_files(folder_id, mime_filter="application/pdf")
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    items = []
    for f in files:
        size_bytes = int(f.get("size", 0))
        size_mb = f"{size_bytes / (1024 * 1024):.2f}" if size_bytes else "0.00"
        company_name, doc_date = _parse_filename(f["name"])

        items.append(PDFFileItem(
            gdrive_file_id=f["id"],
            filename=f["name"],
            company_name=company_name,
            doc_date=doc_date,
            size_bytes=size_bytes,
            size_mb=size_mb,
            created_time=f.get("createdTime"),
            web_view_link=f.get("webViewLink"),
        ))

    return PDFFileListResponse(
        folder_id=folder_id,
        total_files=len(items),
        files=items,
    )


@router.get("/search", response_model=CompanyProfileListResponse, summary="Cari profil perusahaan dari database")
async def search_profiles(q: str = Query(..., min_length=1, description="Nama perusahaan atau kata kunci")):
    """Mencari profil perusahaan yang tersinkronisasi dari Google Sheets."""
    rows = await sheets_service.search_profiles(q)
    return CompanyProfileListResponse(
        total=len(rows),
        profiles=[CompanyProfile(**r) for r in rows],
    )


@router.get("/all", response_model=CompanyProfileListResponse, summary="Daftar seluruh profil perusahaan")
async def get_all_profiles():
    """Menampilkan semua profil perusahaan yang tersinkronisasi dari Google Sheets."""
    rows = await sheets_service.get_all_profiles()
    return CompanyProfileListResponse(
        total=len(rows),
        profiles=[CompanyProfile(**r) for r in rows],
    )


@router.post("/sync", response_model=SyncSheetResponse, summary="Sinkronisasi data profil dari Google Spreadsheet")
async def sync_google_sheets(spreadsheet_id: Optional[str] = Query(None)):
    """
    Menarik data profil terbaru dari Google Spreadsheet ke database SQLite lokal.
    """
    try:
        count = await sheets_service.sync_from_spreadsheet(spreadsheet_id)
        return SyncSheetResponse(
            success=True,
            message=f"Berhasil menyinkronkan {count} profil perusahaan dari Google Spreadsheet.",
            synced_count=count,
        )
    except Exception as e:
        logger.error(f"Gagal sync Google Sheets: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Gagal sinkronisasi Google Spreadsheet: {str(e)}"
        )
