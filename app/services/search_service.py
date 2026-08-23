import time
import logging
from typing import List, Dict, Any, Optional
from app.config import settings

logger = logging.getLogger(__name__)

# Cooldown period (seconds) before retrying ES connection after a failure (15 seconds)
ES_RETRY_COOLDOWN = 15


class SearchService:
    def __init__(self):
        self.es_client = None
        self.index_name = settings.ELASTICSEARCH_INDEX
        self._es_available = False
        self._last_failure_time: float = 0

    async def get_client(self):
        # If ES is not available and failure occurred within cooldown window, fail fast
        if not self._es_available and self._last_failure_time:
            elapsed = time.time() - self._last_failure_time
            if elapsed < ES_RETRY_COOLDOWN:
                return None

        if self.es_client is None:
            try:
                import asyncio
                from elasticsearch import AsyncElasticsearch

                client_kwargs = {
                    "hosts": [settings.ELASTICSEARCH_URL],
                    "request_timeout": 5.0,
                    "retry_on_timeout": True,
                    "max_retries": 2,
                }

                if settings.ELASTICSEARCH_API_KEY and settings.ELASTICSEARCH_API_KEY.strip():
                    client_kwargs["api_key"] = settings.ELASTICSEARCH_API_KEY.strip()

                self.es_client = AsyncElasticsearch(**client_kwargs)
                # Use info() (GET /) instead of ping() (HEAD /) — ES 8.15 returns 400 on HEAD
                es_info = await asyncio.wait_for(self.es_client.info(), timeout=5.0)
                if es_info and es_info.get("version"):
                    logger.info(f"Elasticsearch connected at: {settings.ELASTICSEARCH_URL} (v{es_info['version']['number']})")
                    self._es_available = True
                    self._last_failure_time = 0
                else:
                    logger.warning(f"Elasticsearch info check failed at: {settings.ELASTICSEARCH_URL}")
                    await self.es_client.close()
                    self.es_client = None
                    self._es_available = False
                    self._last_failure_time = time.time()
            except Exception as e:
                logger.warning(f"Elasticsearch not available ({type(e).__name__}: {str(e)}). Using SQLite fallback.")
                if self.es_client:
                    try:
                        await self.es_client.close()
                    except Exception:
                        pass
                self.es_client = None
                self._es_available = False
                self._last_failure_time = time.time()
        return self.es_client

    async def ensure_index(self):
        client = await self.get_client()
        if not client:
            return

        try:
            exists = await client.indices.exists(index=self.index_name)
            if not exists:
                mapping = {
                    "settings": {
                        "analysis": {
                            "analyzer": {
                                "filename_analyzer": {
                                    "type": "custom",
                                    "tokenizer": "standard",
                                    "filter": ["lowercase", "asciifolding"]
                                }
                            }
                        }
                    },
                    "mappings": {
                        "properties": {
                            "id": {"type": "keyword"},
                            "title": {
                                "type": "text",
                                "analyzer": "filename_analyzer",
                                "fields": {
                                    "keyword": {"type": "keyword", "ignore_above": 256}
                                }
                            },
                            "filename": {
                                "type": "text",
                                "analyzer": "filename_analyzer"
                            },
                            "gdrive_link": {"type": "keyword"},
                            "file_type": {"type": "keyword"},
                            "file_size": {"type": "long"},
                            "uploader": {
                                "type": "text",
                                "analyzer": "filename_analyzer",
                                "fields": {
                                    "keyword": {"type": "keyword", "ignore_above": 256}
                                }
                            },
                            "chat_source": {"type": "keyword"},
                            "tags": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                            "description": {"type": "text"},
                            "created_at": {"type": "date", "format": "strict_date_optional_time||epoch_millis||yyyy-MM-dd HH:mm:ss"}
                        }
                    }
                }
                await client.indices.create(index=self.index_name, body=mapping)
                logger.info(f"Elasticsearch index '{self.index_name}' created successfully.")
        except Exception as e:
            logger.error(f"Error ensuring Elasticsearch index: {str(e)}")
            self._mark_unavailable()

    async def rebuild_index(self):
        """Delete and recreate the index, then reindex all documents from SQLite."""
        client = await self.get_client()
        if not client:
            return 0

        try:
            exists = await client.indices.exists(index=self.index_name)
            if exists:
                await client.indices.delete(index=self.index_name)
                logger.info(f"Deleted old index '{self.index_name}'.")
            # Reset client reference so ensure_index creates fresh
            await self.ensure_index()
            return await self.reindex_from_sqlite()
        except Exception as e:
            logger.error(f"Error rebuilding index: {e}")
            return 0

    async def index_document(self, doc_data: Dict[str, Any]) -> bool:
        client = await self.get_client()
        if not client:
            return False

        try:
            await self.ensure_index()
            doc_id = doc_data['id']
            await client.index(index=self.index_name, id=doc_id, document=doc_data, refresh=True)
            logger.info(f"Indexed document {doc_id} into Elasticsearch.")
            return True
        except Exception as e:
            logger.error(f"Failed to index document in Elasticsearch: {str(e)}")
            self._mark_unavailable()
            return False

    async def search_documents(
        self, query: str, page: int = 1, size: int = 10
    ) -> Optional[Dict[str, Any]]:
        client = await self.get_client()
        if not client:
            return None

        from_val = (page - 1) * size
        search_fields = ["title^3", "filename^2", "tags^2", "description", "uploader"]

        # Build wildcard value for partial matching
        wildcard_val = f"*{query.lower()}*"

        search_query = {
            "from": from_val,
            "size": size,
            "query": {
                "bool": {
                    "should": [
                        # 1. Fuzzy multi_match (handles typos)
                        {
                            "multi_match": {
                                "query": query,
                                "fields": search_fields,
                                "fuzziness": "AUTO",
                                "type": "best_fields"
                            }
                        },
                        # 2. Exact phrase match (highest relevance)
                        {
                            "multi_match": {
                                "query": query,
                                "fields": search_fields,
                                "type": "phrase"
                            }
                        },
                        # 3. Wildcard on title (partial match)
                        {
                            "wildcard": {
                                "title": {
                                    "value": wildcard_val,
                                    "boost": 2.0,
                                    "case_insensitive": True
                                }
                            }
                        },
                        # 4. Wildcard on filename (partial match)
                        {
                            "wildcard": {
                                "filename": {
                                    "value": wildcard_val,
                                    "boost": 1.5,
                                    "case_insensitive": True
                                }
                            }
                        }
                    ],
                    "minimum_should_match": 1
                }
            },
            "highlight": {
                "fields": {
                    "title": {},
                    "filename": {},
                    "description": {}
                }
            }
        }

        try:
            res = await client.search(index=self.index_name, body=search_query)
            hits = res['hits']['hits']
            total = res['hits']['total']['value'] if isinstance(res['hits']['total'], dict) else res['hits']['total']

            results = []
            for hit in hits:
                source = hit['_source']
                source['score'] = hit['_score']
                results.append(source)

            return {
                "total": total,
                "results": results
            }
        except Exception as e:
            logger.error(f"Elasticsearch search error: {str(e)}")
            self._mark_unavailable()
            return None

    async def delete_document(self, doc_id: str) -> bool:
        client = await self.get_client()
        if not client:
            return False

        try:
            await client.delete(index=self.index_name, id=doc_id, refresh=True)
            logger.info(f"Deleted document {doc_id} from Elasticsearch.")
            return True
        except Exception as e:
            logger.error(f"Failed to delete document {doc_id} from Elasticsearch: {str(e)}")
            return False

    def _mark_unavailable(self):
        """Mark ES as unavailable and close the client to prevent further retries."""
        self._es_available = False
        self._last_failure_time = time.time()
        if self.es_client:
            try:
                import asyncio
                asyncio.get_event_loop().create_task(self.es_client.close())
            except Exception:
                pass
        self.es_client = None

    async def reindex_from_sqlite(self):
        """Re-index all documents from SQLite into Elasticsearch."""
        client = await self.get_client()
        if not client:
            logger.warning("Cannot reindex: Elasticsearch not available.")
            return 0

        await self.ensure_index()

        import aiosqlite
        from app.config import settings as app_settings

        db_path = app_settings.SQLITE_DB_PATH
        indexed_count = 0

        try:
            async with aiosqlite.connect(db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT COUNT(*) as count FROM documents") as cursor:
                    row = await cursor.fetchone()
                    total = row['count'] if row else 0

                if total == 0:
                    logger.info("No documents in SQLite to reindex.")
                    return 0

                logger.info(f"Starting reindex of {total} documents from SQLite to Elasticsearch...")

                async with db.execute("SELECT * FROM documents") as cursor:
                    async for row in cursor:
                        doc = dict(row)
                        doc_data = {
                            "id": doc["id"],
                            "title": doc.get("title", ""),
                            "filename": doc.get("filename", ""),
                            "gdrive_link": doc.get("gdrive_link", ""),
                            "file_type": doc.get("file_type", ""),
                            "file_size": doc.get("file_size", 0),
                            "uploader": doc.get("uploader", ""),
                            "chat_source": doc.get("chat_source", ""),
                            "tags": doc.get("tags", ""),
                            "description": doc.get("description", ""),
                            "created_at": str(doc.get("created_at", "")),
                        }
                        try:
                            await client.index(
                                index=self.index_name,
                                id=doc_data["id"],
                                document=doc_data,
                            )
                            indexed_count += 1
                        except Exception as e:
                            logger.error(f"Failed to reindex doc {doc_data['id']}: {e}")

                # Refresh index after bulk insert
                await client.indices.refresh(index=self.index_name)
                logger.info(f"Reindex complete: {indexed_count}/{total} documents indexed into Elasticsearch.")

        except Exception as e:
            logger.error(f"Reindex error: {e}")

        return indexed_count


search_service = SearchService()
