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


def _normalize_header(header: str) -> str:
    """Normalize column header for flexible matching."""
    return header.strip().lower().replace("_", " ").replace("-", " ")


class SheetsProfilingService:
    """Service for syncing and querying company profiling data from Google Sheets."""

    async def sync_from_spreadsheet(self, spreadsheet_id: Optional[str] = None) -> int:
        """
        Download CSV from Google Spreadsheet and sync all rows into the company_profiles SQLite table.

        Returns:
            Number of records synced.
        """
        sheet_id = spreadsheet_id or settings.PROFILING_SPREADSHEET_ID
        if not sheet_id:
            raise ValueError(
                "PROFILING_SPREADSHEET_ID belum dikonfigurasi di file .env."
            )

        logger.info(f"Syncing profiling data from Google Spreadsheet ID: {sheet_id}...")
        csv_text = await gdrive_service.export_spreadsheet_csv(sheet_id)

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
