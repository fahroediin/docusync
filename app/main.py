import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import init_db
from app.routers import documents, profiling
from app.services.search_service import search_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup tasks
    logger.info("Initializing DocuSync database...")
    await init_db()
    
    logger.info("Checking Elasticsearch connection...")
    try:
        await search_service.ensure_index()
        # Auto-reindex from SQLite if ES index is empty but SQLite has documents
        es_client = await search_service.get_client()
        if es_client:
            try:
                count_resp = await es_client.count(index=search_service.index_name)
                es_doc_count = count_resp.get("count", 0)
                if es_doc_count == 0:
                    logger.info("Elasticsearch index is empty — auto-reindexing from SQLite...")
                    indexed = await search_service.reindex_from_sqlite()
                    logger.info(f"Auto-reindex done: {indexed} documents indexed.")
                else:
                    logger.info(f"Elasticsearch index has {es_doc_count} documents. Skipping reindex.")
            except Exception as e:
                logger.warning(f"Could not check/reindex ES: {type(e).__name__}: {e}")
    except Exception as e:
        logger.warning(f"Elasticsearch not available on startup (will use SQLite fallback): {type(e).__name__}")

    yield

    # Shutdown tasks — cleanup ES client session
    if search_service.es_client:
        try:
            await search_service.es_client.close()
        except Exception:
            pass
    logger.info("DocuSync server shutting down.")


app = FastAPI(
    title=settings.APP_NAME,
    description="DocuSync — Document Management System with Google Drive integration & Elasticsearch full-text search.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# Enable CORS for frontend and WhatsApp client
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
app.include_router(documents.router)
app.include_router(profiling.router)


@app.get("/", include_in_schema=False)
async def root():
    return {
        "app": settings.APP_NAME,
        "docs": "/docs",
        "health": "/api/v1/health"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG
    )
