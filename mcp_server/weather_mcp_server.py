import os
import logging
from contextvars import ContextVar

from fastmcp import FastMCP
from sentence_transformers import SentenceTransformer
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

import weather_broker
import lakebase

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("weather-mcp-server")

# Load embedding model once at startup
_embedding_model = None

def get_embedding_model():
    """Lazy-load the embedding model (expensive operation, only on first use)."""
    global _embedding_model
    if _embedding_model is None:
        logger.info(f"Loading embedding model: {EMBEDDING_MODEL}")
        _embedding_model = SentenceTransformer(EMBEDDING_MODEL)
    return _embedding_model

# Table names from environment variables
WEATHER_TABLE_NAME = os.environ.get("WEATHER_TABLE_NAME", "weather_documents")
EMBEDDINGS_TABLE_NAME = os.environ.get("EMBEDDINGS_TABLE_NAME", "weather_documents_embeddings")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

# Context variable to store request headers for accessing end-user identity
_request_context: ContextVar[dict] = ContextVar('request_context', default={})

def _get_end_user_email() -> str:
    """Get the actual end user's email from request headers, or fallback to service principal."""
    # Try to get from X-Forwarded-User header (Databricks App context)
    headers = _request_context.get()
    forwarded_user = headers.get('x-forwarded-user')
    if forwarded_user:
        return forwarded_user
    
    # Fallback: use service principal (local development or non-App contexts)
    from databricks.sdk import WorkspaceClient
    w = WorkspaceClient()
    return w.current_user.me().user_name or 'ibrahim.itani02@gmail.com'


mcp = FastMCP("Mateo-weater-recommendation")

class RequestContextMiddleware(BaseHTTPMiddleware):
    """Middleware to capture HTTP headers containing end-user identity."""
    async def dispatch(self, request: Request, call_next):
        # Capture headers that Databricks injects with user identity
        headers = {
            'x-forwarded-user': request.headers.get('x-forwarded-user'),
            'x-forwarded-email': request.headers.get('x-forwarded-email'),
        }
        _request_context.set(headers)
        response = await call_next(request)
        return response
@mcp.tool
def get_current_weather(location: str) -> dict:
    """
    Get the weather conditions from Open-Mateo.

    Args:
        location: city name and state.

    Returns:
        A dict with temperature, conditions, humidity, wind.
    """
    return weather_broker.get_current_weather(location)

@mcp.tool
def get_forecast(location: str, days: float) -> dict:
    """
    Gets a multi day forecast for the next N days.
    
    Args:
        location: city name and state.
        days: number of days required for the forecast.
        
    Returns:
        A dict with temp high/low, precipitation chance, conditions.
    """
    return weather_broker.get_forecast(location, days)

@mcp.tool
def get_travel_recommendation(location: str, date: str) -> dict:
    return weather_broker.get_travel_recommendation(location,date)


def vector_search(query: str, limit: int = 10) -> dict:
    """
    Semantic search over weather news using vector embeddings.
    
    Accepts a text query, computes its embedding, and returns the most similar
    documents and chunks from Lakebase using pgvector's cosine similarity.
    
    Args:
        query: Natural language search query (e.g. "tech company earnings")
        limit: Maximum number of results to return (default 10)
    
    Returns:
        A dict with query, documents, chunks, and model name
    """
    if not query or not query.strip():
        return {"error": "Query text is required"}
    
    try:
        # Compute embedding for the query
        model = get_embedding_model()
        query_embedding = model.encode(query)
        
        # Convert to list for JSON serialization and postgres array format
        embedding_list = query_embedding.tolist()
        
        # Search document-level embeddings
        doc_results = lakebase.run_query(
            f"""
            SELECT 
                e.id,
                e.ticker,
                e.title,
                e.published_utc,
                e.model_name,
                1 - (e.embedding <=> %s::vector) as similarity,
                d.description,
                d.article_url,
                d.sentiment
            FROM {EMBEDDINGS_TABLE_NAME} e
            LEFT JOIN {WEATHER_TABLE_NAME} d ON e.id = d.id
            ORDER BY e.embedding <=> %s::vector
            LIMIT %s
            """,
            (str(embedding_list), str(embedding_list), limit),
        )
        return {
            "query": query,
            "documents": doc_results,
            "model": EMBEDDING_MODEL
        }
        
    except Exception as e:
        logger.exception("Vector search failed")
        return {"error": str(e)}

if __name__ == "__main__":
    # Add middleware to capture request headers for end-user identity
    # This must be done before mcp.run() is called
    if hasattr(mcp, 'app') and mcp.app is not None:
        mcp.app.add_middleware(RequestContextMiddleware)
    
    # Databricks Apps route external HTTP traffic to this port via app.yaml;
    # streamable-http is the transport Databricks' MCP client/gateway expects
    # (see the "Host your own MCP" doc linked in the module docstring above).
    port = int(os.getenv("DATABRICKS_APP_PORT", os.getenv("PORT", 8000)))
    mcp.run(transport="http", host="0.0.0.0", port=port)

    
