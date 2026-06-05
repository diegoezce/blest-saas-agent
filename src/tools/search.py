import logging
import time
from tavily import TavilyClient

logger = logging.getLogger(__name__)

_client: TavilyClient | None = None


def _get_client() -> TavilyClient:
    global _client
    if _client is None:
        from src.config import settings
        _client = TavilyClient(api_key=settings.tavily_api_key)
    return _client


def search(query: str, max_results: int | None = None) -> list[dict]:
    from src.config import settings
    try:
        response = _get_client().search(
            query=query,
            search_depth=settings.tavily_search_depth,
            max_results=max_results or settings.tavily_max_results,
        )
        results = response.get("results", [])
        logger.debug(f"Tavily '{query[:60]}' → {len(results)} results")
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("content", ""),
                "score": r.get("score", 0.0),
                "query": query,
            }
            for r in results
        ]
    except Exception as e:
        logger.error(f"Tavily search failed for '{query[:60]}': {e}")
        return []


def batch_search(queries: list[str], batch_size: int = 3, delay: float = 1.0) -> list[dict]:
    all_results: list[dict] = []
    seen_urls: set[str] = set()

    for i in range(0, len(queries), batch_size):
        batch = queries[i : i + batch_size]
        for query in batch:
            for r in search(query):
                if r["url"] not in seen_urls:
                    seen_urls.add(r["url"])
                    all_results.append(r)
        if i + batch_size < len(queries):
            time.sleep(delay)

    logger.info(f"Batch search: {len(queries)} queries → {len(all_results)} unique results")
    return all_results
