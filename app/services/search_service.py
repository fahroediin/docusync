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

                headers = {}
                if settings.ELASTICSEARCH_API_KEY:
                    headers['Authorization'] = f"ApiKey {settings.ELASTICSEARCH_API_KEY}"

                self.es_client = AsyncElasticsearch(
                    settings.ELASTICSEARCH_URL,
                    headers=headers,
                    request_timeout=3.0,
                    retry_on_timeout=True,
                    max_retries=1,
                )
                # Quick 2.0s ping test
                if await asyncio.wait_for(self.es_client.ping(), timeout=2.0):
                    logger.info(f"Elasticsearch connected at: {settings.ELASTICSEARCH_URL}")
                    self._es_available = True
                    self._last_failure_time = 0
                else:
                    logger.warning(f"Elasticsearch ping failed at: {settings.ELASTICSEARCH_URL}")
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
                    "mappings": {
                        "properties": {
                            "id": {"type": "keyword"},
                            "title": {
                                "type": "text",
                                "analyzer": "standard",
                                "fields": {
                                    "keyword": {"type": "keyword", "ignore_above": 256}
                                }
                            },
                            "filename": {"type": "text"},
                            "gdrive_link": {"type": "keyword"},
                            "file_type": {"type": "keyword"},
                            "file_size": {"type": "long"},
                            "uploader": {"type": "keyword"},
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

        search_query = {
            "from": from_val,
            "size": size,
            "query": {
                "multi_match": {
                    "query": query,
                    "fields": ["title^3", "filename^2", "tags^2", "description", "uploader"],
                    "fuzziness": "AUTO"
                }
            },
            "highlight": {
                "fields": {
                    "title": {},
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


search_service = SearchService()
