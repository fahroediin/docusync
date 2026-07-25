import uuid
import logging
from typing import List, Dict, Any, Optional
import aiosqlite
from datetime import datetime
from app.config import settings

logger = logging.getLogger(__name__)


class DatabaseService:
    @staticmethod
    async def create_document(db: aiosqlite.Connection, doc_data: Dict[str, Any]) -> Dict[str, Any]:
        doc_id = doc_data.get('id') or str(uuid.uuid4())
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        query = """
            INSERT INTO documents (
                id, title, filename, gdrive_file_id, gdrive_link,
                file_type, file_size, uploader, chat_source, tags, description, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        await db.execute(query, (
            doc_id,
            doc_data.get('title'),
            doc_data.get('filename'),
            doc_data.get('gdrive_file_id'),
            doc_data.get('gdrive_link'),
            doc_data.get('file_type'),
            doc_data.get('file_size', 0),
            doc_data.get('uploader', 'System'),
            doc_data.get('chat_source', 'Direct Upload'),
            doc_data.get('tags', ''),
            doc_data.get('description', ''),
            now,
            now
        ))
        await db.commit()

        return await DatabaseService.get_document(db, doc_id)

    @staticmethod
    async def get_document(db: aiosqlite.Connection, doc_id: str) -> Optional[Dict[str, Any]]:
        async with db.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return None

    @staticmethod
    async def get_documents(
        db: aiosqlite.Connection, page: int = 1, size: int = 10
    ) -> Dict[str, Any]:
        offset = (page - 1) * size

        async with db.execute("SELECT COUNT(*) as count FROM documents") as cursor:
            row = await cursor.fetchone()
            total = row['count'] if row else 0

        async with db.execute(
            "SELECT * FROM documents ORDER BY created_at DESC LIMIT ? OFFSET ?", (size, offset)
        ) as cursor:
            rows = await cursor.fetchall()
            documents = [dict(row) for row in rows]

        return {
            "total": total,
            "page": page,
            "size": size,
            "documents": documents
        }

    @staticmethod
    async def search_documents_sqlite(
        db: aiosqlite.Connection, query_str: str, page: int = 1, size: int = 10
    ) -> Dict[str, Any]:
        offset = (page - 1) * size
        like_pattern = f"%{query_str}%"

        count_query = """
            SELECT COUNT(*) as count FROM documents 
            WHERE title LIKE ? OR filename LIKE ? OR tags LIKE ? OR description LIKE ? OR uploader LIKE ?
        """
        async with db.execute(count_query, (like_pattern, like_pattern, like_pattern, like_pattern, like_pattern)) as cursor:
            row = await cursor.fetchone()
            total = row['count'] if row else 0

        select_query = """
            SELECT * FROM documents 
            WHERE title LIKE ? OR filename LIKE ? OR tags LIKE ? OR description LIKE ? OR uploader LIKE ?
            ORDER BY created_at DESC LIMIT ? OFFSET ?
        """
        async with db.execute(select_query, (like_pattern, like_pattern, like_pattern, like_pattern, like_pattern, size, offset)) as cursor:
            rows = await cursor.fetchall()
            documents = [dict(row) for row in rows]

        return {
            "total": total,
            "page": page,
            "size": size,
            "documents": documents
        }

    @staticmethod
    async def delete_document(db: aiosqlite.Connection, doc_id: str) -> bool:
        cursor = await db.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        await db.commit()
        return cursor.rowcount > 0

    @staticmethod
    async def find_duplicate_file(
        db: aiosqlite.Connection, filename: str, file_size: int
    ) -> Optional[Dict[str, Any]]:
        """Find existing document with matching filename and file_size."""
        query = "SELECT * FROM documents WHERE filename = ? AND file_size = ? LIMIT 1"
        async with db.execute(query, (filename, file_size)) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return None

    @staticmethod
    async def find_duplicate_link(
        db: aiosqlite.Connection, gdrive_link: str, gdrive_file_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Find existing document with matching link or GDrive file ID."""
        if gdrive_file_id and gdrive_file_id.strip():
            query = "SELECT * FROM documents WHERE gdrive_link = ? OR (gdrive_file_id != '' AND gdrive_file_id = ?) LIMIT 1"
            async with db.execute(query, (gdrive_link.strip(), gdrive_file_id.strip())) as cursor:
                row = await cursor.fetchone()
                if row:
                    return dict(row)
        else:
            query = "SELECT * FROM documents WHERE gdrive_link = ? LIMIT 1"
            async with db.execute(query, (gdrive_link.strip(),)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return dict(row)
        return None


database_service = DatabaseService()

