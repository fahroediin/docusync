import os
import uuid
import aiofiles
import logging
from typing import Optional, List
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
import aiosqlite

from app.config import settings
from app.database import get_db
from app.models.document import DocumentResponse, UploadResponse, SearchResponse, DocumentSearchResult, WhatsAppMediaPayload, LinkPayload
from app.services.gdrive_service import gdrive_service
from app.services.search_service import search_service
from app.services.database_service import database_service
from app.services.wa_decrypt_service import download_and_decrypt_wa_media

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Documents"])


async def fetch_html_title(url: str) -> Optional[str]:
    import httpx, re
    try:
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
            res = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            if res.status_code == 200:
                match = re.search(r'<title[^>]*>(.*?)</title>', res.text, re.IGNORECASE | re.DOTALL)
                if match:
                    title = match.group(1).strip()
                    # Clean up Google web suffixes
                    title = re.sub(r'\s*-\s*Google\s+(Docs|Sheets|Slides|Drive|Forms)\s*$', '', title, flags=re.IGNORECASE)
                    return title.strip()
    except Exception:
        pass
    return None


@router.get("/health")
async def health_check():
    es_status = False
    try:
        es_client = await search_service.get_client()
        if es_client is not None:
            es_info = await es_client.info()
            es_status = bool(es_info and es_info.get("version"))
    except Exception:
        es_status = False

    return {
        "status": "online",
        "app_name": settings.APP_NAME,
        "gdrive_configured": gdrive_service.is_configured(),
        "elasticsearch_online": es_status,
        "sqlite_path": settings.SQLITE_DB_PATH,
        "allowed_file_extensions": settings.allowed_extensions_list
    }


@router.post("/link/save", response_model=UploadResponse, summary="Simpan Metadata Shared Google Drive/Docs Link Tanpa Upload File")
async def save_shared_link(
    payload: LinkPayload,
    db: aiosqlite.Connection = Depends(get_db)
):
    """
    Menyimpan link dokumen/spreadsheet Google Drive yang dibagikan pengguna.
    Sistem membaca nama/judul dokumen secara otomatis via GDrive API atau HTML title tag,
    lalu mengindeksnya ke SQLite & Elasticsearch.
    """
    url = payload.url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        raise HTTPException(status_code=400, detail="URL tidak valid.")

    file_id = gdrive_service.extract_file_id_from_url(url) or ""

    # Check for duplicate link
    existing_link = await database_service.find_duplicate_link(db, url, file_id)
    if existing_link:
        return UploadResponse(
            success=True,
            message="Link dokumen ini sudah pernah disimpan sebelumnya.",
            document=DocumentResponse(**existing_link)
        )

    doc_title = payload.title.strip() if payload.title and payload.title.strip() else None
    mime_type = "url/link"

    # 1. Try fetching document title via Google Drive API if file_id exists
    if file_id:
        gdrive_info = await gdrive_service.get_file_info(file_id)
        if gdrive_info:
            if not doc_title and gdrive_info.get('name'):
                doc_title = gdrive_info['name']
            if gdrive_info.get('mimeType'):
                mime_type = gdrive_info['mimeType']

    # 2. Fallback: Try fetching title from HTML <title> tag
    if not doc_title:
        doc_title = await fetch_html_title(url)

    # 3. Final Fallback: URL string
    if not doc_title:
        doc_title = f"Link Dokumen ({file_id or url[:40]})"

    # Save to SQLite
    doc_data = {
        "id": str(uuid.uuid4()),
        "title": doc_title,
        "filename": doc_title,
        "gdrive_file_id": file_id,
        "gdrive_link": url,
        "file_type": mime_type,
        "file_size": 0,
        "uploader": payload.uploader or "WhatsApp User",
        "chat_source": payload.chat_source or "WhatsApp Chat",
        "tags": payload.tags or "",
        "description": payload.description or ""
    }

    saved_doc = await database_service.create_document(db, doc_data)

    # Index in Elasticsearch
    try:
        await search_service.index_document(saved_doc)
    except Exception as es_err:
        logger.warning(f"Failed to index link document in Elasticsearch: {str(es_err)}")

    return UploadResponse(
        success=True,
        message="Link dokumen berhasil disimpan dan diindeks.",
        document=DocumentResponse(**saved_doc)
    )


@router.post("/send/media", response_model=UploadResponse, summary="Direct Server-Side WhatsApp Media Download & Decrypt")
async def send_whatsapp_media(
    payload: WhatsAppMediaPayload,
    db: aiosqlite.Connection = Depends(get_db)
):
    """
    Endpoint khusus untuk WhatsApp Bot.
    Bot mengirim metadata media (directPath, mediaKey, url, mimetype, filename) ke endpoint ini.
    Server yang melakukan download langsung dari CDN WhatsApp, dekripsi AES, upload ke GDrive, & index DB.
    Mem-bypass bug downloadMedia() pada whatsapp-web.js.
    """
    if not payload.mediaKey:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="mediaKey wajib diisi untuk mendeskripsi media WhatsApp."
        )

    # 1. Download & Decrypt from WhatsApp CDN
    try:
        decrypted_content = await download_and_decrypt_wa_media(
            media_key=payload.mediaKey,
            direct_path=payload.directPath,
            url=payload.url,
            media_type=payload.mediaType or "document"
        )
    except Exception as e:
        logger.error(f"Gagal download & decrypt WA media: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Gagal mengunduh/mendekripsi media WhatsApp: {str(e)}"
        )

    # 2. Determine Filename & Validate Extension
    filename = payload.filename or f"Dokumen_{uuid.uuid4().hex[:8]}.pdf"
    file_ext = os.path.splitext(filename)[1].lstrip(".").lower()
    allowed_exts = settings.allowed_extensions_list

    if allowed_exts and file_ext not in allowed_exts:
        allowed_str = ", ".join(allowed_exts).upper()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tipe file '.{file_ext}' tidak diizinkan. Hanya file ({allowed_str}) yang diterima."
        )

    file_size = len(decrypted_content)
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if file_size > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Ukuran file ({round(file_size / (1024*1024), 2)} MB) melebihi batas maksimal {settings.MAX_UPLOAD_SIZE_MB} MB."
        )

    # Check for duplicate document before GDrive upload
    doc_title = payload.title if payload.title and payload.title.strip() else filename
    existing_doc = await database_service.find_duplicate_file(db, filename, file_size)
    if existing_doc:
        logger.info(f"Duplicate document detected for '{filename}' ({file_size} bytes). Skipping GDrive upload.")
        return UploadResponse(
            success=True,
            message="Dokumen ini sudah pernah disimpan sebelumnya.",
            document=DocumentResponse(**existing_doc)
        )

    temp_dir = settings.TEMP_STORAGE_DIR
    os.makedirs(temp_dir, exist_ok=True)
    temp_file_path = os.path.join(temp_dir, f"{uuid.uuid4()}_{filename}")

    try:
        async with aiofiles.open(temp_file_path, 'wb') as out_file:
            await out_file.write(decrypted_content)

        mimetype = payload.mimetype or "application/octet-stream"

        # 3. Upload to Google Drive
        try:
            gdrive_result = await gdrive_service.upload_file(
                file_path=temp_file_path,
                filename=doc_title,
                mimetype=mimetype
            )
        except Exception as e:
            logger.error(f"Google Drive upload failed: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Gagal mengunggah file ke Google Drive: {str(e)}"
            )

        # 4. Save metadata to SQLite
        doc_data = {
            "id": str(uuid.uuid4()),
            "title": doc_title,
            "filename": filename,
            "gdrive_file_id": gdrive_result['file_id'],
            "gdrive_link": gdrive_result['web_view_link'],
            "file_type": mimetype,
            "file_size": file_size,
            "uploader": payload.uploader or "WhatsApp User",
            "chat_source": payload.chat_source or "WhatsApp Chat",
            "tags": payload.tags or "",
            "description": payload.description or ""
        }

        saved_doc = await database_service.create_document(db, doc_data)

        # 5. Index in Elasticsearch
        try:
            await search_service.index_document(saved_doc)
        except Exception as es_err:
            logger.warning(f"Failed to index document in Elasticsearch: {str(es_err)}")

        return UploadResponse(
            success=True,
            message="Dokumen dari WhatsApp berhasil diunduh, dideskripsi, dan disimpan ke Google Drive.",
            document=DocumentResponse(**saved_doc)
        )

    finally:
        if os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except Exception:
                pass



@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),
    uploader: Optional[str] = Form("System"),
    chat_source: Optional[str] = Form("Direct Upload"),
    db: aiosqlite.Connection = Depends(get_db)
):
    # Validate file extension against ALLOWED_FILE_EXTENSIONS
    file_ext = os.path.splitext(file.filename or "")[1].lstrip(".").lower()
    allowed_exts = settings.allowed_extensions_list
    
    if allowed_exts and file_ext not in allowed_exts:
        allowed_str = ", ".join(allowed_exts).upper()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tipe file '.{file_ext}' tidak diizinkan. Hanya file ({allowed_str}) yang diterima."
        )

    temp_dir = settings.TEMP_STORAGE_DIR
    os.makedirs(temp_dir, exist_ok=True)
    
    unique_file_name = f"{uuid.uuid4()}_{file.filename}"
    temp_file_path = os.path.join(temp_dir, unique_file_name)

    try:
        # Save file to temp staging area
        async with aiofiles.open(temp_file_path, 'wb') as out_file:
            content = await file.read()
            await out_file.write(content)

        file_size = os.path.getsize(temp_file_path)
        max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        if file_size > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Ukuran file ({round(file_size / (1024*1024), 2)} MB) melebihi batas maksimal {settings.MAX_UPLOAD_SIZE_MB} MB."
            )

        doc_title = title if title and title.strip() else file.filename
        mimetype = file.content_type or "application/octet-stream"

        # Check for duplicate document before GDrive upload
        existing_doc = await database_service.find_duplicate_file(db, file.filename, file_size)
        if existing_doc:
            logger.info(f"Duplicate upload detected for '{file.filename}' ({file_size} bytes). Skipping GDrive upload.")
            return UploadResponse(
                success=True,
                message="Dokumen ini sudah pernah disimpan sebelumnya.",
                document=DocumentResponse(**existing_doc)
            )

        # 1. Upload to Google Drive
        gdrive_result = None
        try:
            gdrive_result = await gdrive_service.upload_file(
                file_path=temp_file_path,
                filename=doc_title,
                mimetype=mimetype
            )
        except Exception as e:
            logger.error(f"Google Drive upload failed: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Gagal mengunggah file ke Google Drive: {str(e)}"
            )

        # 2. Save metadata to SQLite
        doc_data = {
            "id": str(uuid.uuid4()),
            "title": doc_title,
            "filename": file.filename,
            "gdrive_file_id": gdrive_result['file_id'],
            "gdrive_link": gdrive_result['web_view_link'],
            "file_type": mimetype,
            "file_size": file_size,
            "uploader": uploader,
            "chat_source": chat_source,
            "tags": tags or "",
            "description": description or ""
        }

        saved_doc = await database_service.create_document(db, doc_data)

        # 3. Index in Elasticsearch (Async / non-blocking fallback)
        try:
            await search_service.index_document(saved_doc)
        except Exception as es_err:
            logger.warning(f"Failed to index document in Elasticsearch: {str(es_err)}")

        return UploadResponse(
            success=True,
            message="Dokumen berhasil diunggah dan disimpan.",
            document=DocumentResponse(**saved_doc)
        )

    finally:
        # Clean up temp file
        if os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except Exception:
                pass


@router.get("/search", response_model=SearchResponse)
async def search_documents(
    q: str = Query(..., min_length=1, description="Kata kunci pencarian judul/metadata"),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    db: aiosqlite.Connection = Depends(get_db)
):
    # Try Elasticsearch first
    es_result = await search_service.search_documents(query=q, page=page, size=size)

    if es_result is not None:
        results = [
            DocumentSearchResult(
                id=doc['id'],
                title=doc.get('title', ''),
                gdrive_link=doc.get('gdrive_link', ''),
                file_type=doc.get('file_type'),
                file_size=doc.get('file_size', 0),
                uploader=doc.get('uploader'),
                chat_source=doc.get('chat_source'),
                tags=doc.get('tags'),
                description=doc.get('description'),
                score=doc.get('score', 0.0),
                created_at=str(doc.get('created_at', ''))
            )
            for doc in es_result['results']
        ]
        return SearchResponse(
            query=q,
            total=es_result['total'],
            page=page,
            size=size,
            results=results
        )

    # Fallback to SQLite LIKE search if ES is unavailable
    logger.info("Using SQLite search fallback for query: " + q)
    sqlite_result = await database_service.search_documents_sqlite(db, query_str=q, page=page, size=size)
    
    results = [
        DocumentSearchResult(
            id=doc['id'],
            title=doc['title'],
            gdrive_link=doc['gdrive_link'],
            file_type=doc.get('file_type'),
            file_size=doc.get('file_size', 0),
            uploader=doc.get('uploader'),
            chat_source=doc.get('chat_source'),
            tags=doc.get('tags'),
            description=doc.get('description'),
            score=1.0,
            created_at=str(doc.get('created_at', ''))
        )
        for doc in sqlite_result['documents']
    ]

    return SearchResponse(
        query=q,
        total=sqlite_result['total'],
        page=page,
        size=size,
        results=results
    )


@router.get("/documents")
async def list_documents(
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    db: aiosqlite.Connection = Depends(get_db)
):
    return await database_service.get_documents(db, page=page, size=size)


@router.get("/documents/{doc_id}", response_model=DocumentResponse)
async def get_document(doc_id: str, db: aiosqlite.Connection = Depends(get_db)):
    doc = await database_service.get_document(db, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Dokumen tidak ditemukan")
    return DocumentResponse(**doc)


@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: str, db: aiosqlite.Connection = Depends(get_db)):
    doc = await database_service.get_document(db, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Dokumen tidak ditemukan.")

    # 1. Delete from Google Drive if file was uploaded to GDrive
    gdrive_file_id = doc.get('gdrive_file_id')
    if gdrive_file_id and gdrive_file_id.strip():
        try:
            await gdrive_service.delete_file(gdrive_file_id.strip())
        except Exception as g_err:
            logger.warning(f"Gagal menghapus file dari GDrive ({gdrive_file_id}): {str(g_err)}")

    # 2. Delete from Elasticsearch
    try:
        await search_service.delete_document(doc_id)
    except Exception as es_err:
        logger.warning(f"Gagal menghapus dokumen dari Elasticsearch ({doc_id}): {str(es_err)}")

    # 3. Delete from SQLite
    deleted = await database_service.delete_document(db, doc_id)
    if not deleted:
        raise HTTPException(status_code=500, detail="Gagal menghapus dokumen dari database.")

    return {
        "success": True,
        "message": f"Dokumen '{doc.get('title')}' berhasil dihapus dari database & Google Drive.",
        "deleted_document": doc
    }


@router.post("/sync", summary="Sinkronisasi Dokumen dengan Google Drive")
async def sync_gdrive_documents(db: aiosqlite.Connection = Depends(get_db)):
    """
    Memeriksa semua dokumen di SQLite/Elasticsearch terhadap Google Drive.
    Jika file telah dihapus secara manual di Google Drive, data pada SQLite & Elasticsearch akan dibersihkan.
    """
    all_docs = await database_service.get_documents(db, page=1, size=1000)
    docs_list = all_docs.get("documents", [])

    total_checked = 0
    total_cleaned = 0
    cleaned_titles = []

    for doc in docs_list:
        gdrive_file_id = doc.get("gdrive_file_id")
        if not gdrive_file_id or not gdrive_file_id.strip():
            continue

        total_checked += 1
        exists = await gdrive_service.check_file_exists(gdrive_file_id.strip())
        if not exists:
            doc_id = doc["id"]
            await database_service.delete_document(db, doc_id)
            try:
                await search_service.delete_document(doc_id)
            except Exception:
                pass
            total_cleaned += 1
            cleaned_titles.append(doc.get("title") or doc_id)

    return {
        "success": True,
        "total_checked": total_checked,
        "total_cleaned": total_cleaned,
        "cleaned_titles": cleaned_titles,
        "message": f"Sinkronisasi selesai. {total_cleaned} dari {total_checked} dokumen terhapus di GDrive telah dibersihkan."
    }


