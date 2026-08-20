import csv
import io
import uuid
import logging
from typing import List, Optional, Dict, Any
import aiosqlite

from app.config import settings
from app.database import get_db
from app.services.gdrive_service import gdrive_service

logger = logging.getLogger(__name__)


import re


def _parse_spreadsheet_ref(ref: str) -> tuple[str, Optional[str]]:
    """
    Extract spreadsheet ID and optional gid from plain ID or Google Sheets URL.
    Example URL: https://docs.google.com/spreadsheets/d/your_spreadsheet_id/edit?gid=your_tab_gid
    """
    if not ref:
        return "", None

    # Check for ID in URL format
    match_id = re.search(r'/d/([a-zA-Z0-9_-]+)', ref)
    sheet_id = match_id.group(1) if match_id else ref.strip()

    # Check for gid in URL or fragment
    match_gid = re.search(r'[?&#]gid=([0-9]+)', ref)
    gid = match_gid.group(1) if match_gid else None

    return sheet_id, gid


def _normalize_header(header: str) -> str:
    """Normalize column header for flexible matching."""
    return header.strip().lower().replace("_", " ").replace("-", " ")


class SheetsProfilingService:
    """Service for syncing and querying company profiling data from Google Sheets."""

    async def sync_from_spreadsheet(
        self,
        spreadsheet_id: Optional[str] = None,
        gid: Optional[str] = None
    ) -> int:
        """
        Download CSV from Google Spreadsheet (supports specific tab via gid)
        and sync all rows into the company_profiles SQLite table.

        Returns:
            Number of records synced.
        """
        raw_input = spreadsheet_id or settings.PROFILING_SPREADSHEET_ID
        if not raw_input:
            raise ValueError(
                "PROFILING_SPREADSHEET_ID belum dikonfigurasi di file .env."
            )

        # Parse ID and GID from input or config
        sheet_id, extracted_gid = _parse_spreadsheet_ref(raw_input)
        target_gid = gid or extracted_gid or settings.PROFILING_SPREADSHEET_GID or None

        logger.info(
            f"Syncing profiling data from Google Spreadsheet ID: {sheet_id} "
            f"(gid={target_gid or 'default'})..."
        )
        csv_text = await gdrive_service.export_spreadsheet_csv(sheet_id, gid=target_gid)

        # Parse CSV
        reader = csv.DictReader(io.StringIO(csv_text))
        if not reader.fieldnames:
            logger.warning("Spreadsheet CSV is empty or has no header row.")
            return 0

        # Build column mapping
        header_map: Dict[str, str] = {}
        for original in reader.fieldnames:
            norm = _normalize_header(original)
            if any(k in norm for k in ["perusahaan", "company", "nama", "name", "client", "vendor", "mitra"]):
                header_map["company_name"] = original
            elif any(k in norm for k in ["tanggal", "tgl", "date", "waktu"]):
                header_map["doc_date"] = original
            elif any(k in norm for k in ["kategori", "bidang", "jenis", "sektor", "category"]):
                header_map["category"] = original
            elif any(k in norm for k in ["ringkasan", "profil", "summary", "keterangan", "deskripsi", "catatan"]):
                header_map["summary"] = original
            elif any(k in norm for k in ["pic", "kontak", "contact", "penanggung"]):
                header_map["pic"] = original
            elif any(k in norm for k in ["link", "url", "drive", "gdrive", "tautan"]):
                header_map["gdrive_link"] = original

        # Default company_name to first column if not found
        if "company_name" not in header_map and reader.fieldnames:
            header_map["company_name"] = reader.fieldnames[0]

        rows_to_insert = []
        for row in reader:
            company_name = row.get(header_map.get("company_name", ""), "").strip()
            if not company_name:
                continue

            doc_date = row.get(header_map.get("doc_date", ""), "").strip()
            category = row.get(header_map.get("category", ""), "").strip()
            summary = row.get(header_map.get("summary", ""), "").strip()
            pic = row.get(header_map.get("pic", ""), "").strip()
            gdrive_link = row.get(header_map.get("gdrive_link", ""), "").strip()

            # Any unmapped columns can be gathered into extra_info
            extra_cols = [
                f"{k}: {v.strip()}" for k, v in row.items()
                if k not in header_map.values() and v and v.strip()
            ]
            extra_info = " | ".join(extra_cols) if extra_cols else None

            rows_to_insert.append((
                str(uuid.uuid4()),
                company_name,
                doc_date or None,
                category or None,
                summary or None,
                pic or None,
                gdrive_link or None,
                extra_info or None,
            ))

        # Atomic refresh in SQLite
        db_path = settings.SQLITE_DB_PATH
        async with aiosqlite.connect(db_path) as db:
            await db.execute("DELETE FROM company_profiles")
            await db.executemany(
                """INSERT INTO company_profiles
                   (id, company_name, doc_date, category, summary, pic, gdrive_link, extra_info)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                rows_to_insert
            )
            await db.commit()

        logger.info(f"Successfully synced {len(rows_to_insert)} company profiles from Google Sheets.")
        return len(rows_to_insert)

    async def search_profiles(self, query: str) -> List[Dict[str, Any]]:
        """Search company profiles by company name or keyword."""
        db_path = settings.SQLITE_DB_PATH
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            pattern = f"%{query.strip()}%"
            async with db.execute(
                """SELECT * FROM company_profiles
                   WHERE company_name LIKE ?
                      OR category LIKE ?
                      OR summary LIKE ?
                      OR pic LIKE ?
                   ORDER BY company_name ASC""",
                (pattern, pattern, pattern, pattern)
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

    async def get_all_profiles(self) -> List[Dict[str, Any]]:
        """Get all company profiles."""
        db_path = settings.SQLITE_DB_PATH
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM company_profiles ORDER BY company_name ASC"
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]


sheets_service = SheetsProfilingService()
