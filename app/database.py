import os
import aiosqlite
import logging
from app.config import settings

logger = logging.getLogger(__name__)


async def get_db():
    db_path = settings.SQLITE_DB_PATH
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        yield db


async def init_db():
    db_path = settings.SQLITE_DB_PATH
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    async with aiosqlite.connect(db_path) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                filename TEXT NOT NULL,
                gdrive_file_id TEXT NOT NULL,
                gdrive_link TEXT NOT NULL,
                file_type TEXT,
                file_size INTEGER,
                uploader TEXT,
                chat_source TEXT,
                tags TEXT,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # Index on created_at and uploader for faster metadata filtering
        await db.execute("CREATE INDEX IF NOT EXISTS idx_documents_created_at ON documents(created_at DESC);")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_documents_uploader ON documents(uploader);")

        # ── Company Profiles Table (Google Sheets Profiling Sync) ──
        await db.execute("""
            CREATE TABLE IF NOT EXISTS company_profiles (
                id TEXT PRIMARY KEY,
                company_name TEXT NOT NULL,
                doc_date TEXT,
                category TEXT,
                summary TEXT,
                pic TEXT,
                gdrive_link TEXT,
                extra_info TEXT,
                synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_company_profiles_name ON company_profiles(company_name);")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_company_profiles_category ON company_profiles(category);")

        await db.commit()
        logger.info(f"SQLite database initialized at: {db_path}")
