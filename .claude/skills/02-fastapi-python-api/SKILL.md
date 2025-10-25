---
name: fastapi-python-api-design
description: RESTful API design patterns, async best practices, authentication, and error handling for Onyx backend services. Use when creating new API endpoints, modifying request handlers, or implementing authentication flows.
---

# FastAPI/Python API Design Skill for Onyx

## Overview

This skill covers FastAPI patterns and best practices used in the Onyx backend API. Onyx uses FastAPI for its high performance, automatic validation, and excellent async support. The API serves the Next.js frontend and handles authentication, document operations, search queries, and admin functions.

## Architecture Context

**Onyx API Structure:**
- **Framework**: FastAPI with Pydantic for validation
- **Async**: Heavy use of async/await for I/O operations
- **Authentication**: Session-based + OAuth2/SSO
- **Database**: SQLAlchemy async sessions
- **Location**: `backend/danswer/server/` directory

**Key API Modules:**
- `backend/onyx/server/documents/` - Document operations
- `backend/onyx/server/query_and_chat/` - Search and chat endpoints
- `backend/onyx/server/manage/` - Admin endpoints
- `backend/onyx/server/users.py` - User management
- `backend/onyx/auth/` - Authentication logic

## FastAPI Application Setup

### Main Application Structure

```python
# backend/onyx/main.py pattern
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from contextlib import asynccontextmanager

from onyx.configs.app_configs import APP_HOST, APP_PORT
from onyx.server.documents.document import router as document_router
from onyx.server.query_and_chat.query import router as query_router
from onyx.server.manage.admin import router as admin_router
from onyx.db.engine import warm_up_connections

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for startup/shutdown events.
    Onyx pattern for connection management.
    """
    # Startup: warm up database connections
    await warm_up_connections()
    
    yield
    
    # Shutdown: cleanup resources
    await cleanup_resources()

def get_application() -> FastAPI:
    """
    Create and configure FastAPI application.
    
    Onyx configuration pattern:
    - CORS for frontend
    - GZip compression
    - API versioning via prefix
    - Health check endpoint
    """
    app = FastAPI(
        title="Onyx API",
        version="1.0.0",
        description="AI platform for enterprise search and chat",
        lifespan=lifespan
    )
    
    # CORS middleware for frontend
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],  # Frontend dev
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Compression middleware
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    
    # Include routers with prefixes
    app.include_router(document_router, prefix="/api/documents", tags=["documents"])
    app.include_router(query_router, prefix="/api/query", tags=["search"])
    app.include_router(admin_router, prefix="/api/admin", tags=["admin"])
    
    # Health check
    @app.get("/health")
    async def health_check():
        return {"status": "healthy"}
    
    return app

app = get_application()
```

## Request/Response Models with Pydantic

### Model Design Patterns

```python
from pydantic import BaseModel, Field, validator
from typing import Optional, List
from datetime import datetime
from enum import Enum

# Onyx pattern: Enums for constrained values
class DocumentSource(str, Enum):
    GOOGLE_DRIVE = "google_drive"
    SLACK = "slack"
    CONFLUENCE = "confluence"
    LOCAL = "local"
    WEB = "web"

# Request model
class DocumentUploadRequest(BaseModel):
    """
    Request model for document upload.
    
    Onyx patterns:
    - Use Field() for validation and documentation
    - Add examples for API docs
    - Validators for complex logic
    """
    file_name: str = Field(..., description="Name of the file")
    content: str = Field(..., min_length=1, description="Document content")
    source: DocumentSource = Field(default=DocumentSource.LOCAL)
    metadata: Optional[dict] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list, max_items=10)
    
    @validator('tags')
    def validate_tags(cls, v):
        """Ensure tags are lowercase and trimmed."""
        return [tag.lower().strip() for tag in v if tag.strip()]
    
    class Config:
        schema_extra = {
            "example": {
                "file_name": "project_spec.pdf",
                "content": "Project requirements...",
                "source": "local",
                "metadata": {"author": "john@company.com"},
                "tags": ["engineering", "specs"]
            }
        }

# Response model
class DocumentResponse(BaseModel):
    """
    Response model for document operations.
    
    Onyx pattern: Separate request/response models
    even if similar to avoid leaking internal fields.
    """
    id: str = Field(..., description="Document ID")
    file_name: str
    source: DocumentSource
    indexed_at: datetime
    chunk_count: int = Field(..., description="Number of chunks created")
    status: str = Field(..., description="indexing, completed, failed")
    
    class Config:
        orm_mode = True  # Enable from_orm() for SQLAlchemy models

# Nested models for complex responses
class SearchResult(BaseModel):
    document_id: str
    chunk_id: int
    content: str
    score: float
    title: Optional[str] = None
    source: DocumentSource
    
class SearchResponse(BaseModel):
    """Search results with metadata."""
    query: str
    results: List[SearchResult]
    total_results: int
    search_time_ms: float
    applied_filters: dict
```

### Input Validation Patterns

```python
from pydantic import validator, root_validator, constr, conint
from typing import Any

class ChatRequest(BaseModel):
    """
    Chat request with comprehensive validation.
    
    Onyx validation patterns:
    - Constrained types (constr, conint)
    - Field validators
    - Root validators for cross-field validation
    """
    message: constr(min_length=1, max_length=4000) = Field(
        ...,
        description="User message"
    )
    conversation_id: Optional[str] = None
    model: str = Field(default="gpt-4", description="LLM model to use")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: conint(ge=1, le=4000) = 2000
    document_ids: Optional[List[str]] = Field(default=None, max_items=50)
    stream: bool = False
    
    @validator('model')
    def validate_model(cls, v):
        """Ensure model is supported."""
        allowed_models = ["gpt-4", "gpt-3.5-turbo", "claude-3-sonnet"]
        if v not in allowed_models:
            raise ValueError(f"Model must be one of {allowed_models}")
        return v
    
    @root_validator
    def validate_streaming(cls, values):
        """Cross-field validation."""
        if values.get('stream') and values.get('max_tokens', 0) > 3000:
            raise ValueError("Streaming not recommended for responses > 3000 tokens")
        return values
```

## Async Patterns and Best Practices

### Async Route Handlers

```python
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from onyx.db.engine import get_async_session

router = APIRouter()

@router.post("/documents", response_model=DocumentResponse)
async def upload_document(
    request: DocumentUploadRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_current_user)
):
    """
    Upload and index a document.
    
    Onyx async patterns:
    - All I/O operations are async
    - Use dependencies for common operations
    - Background tasks for long-running operations
    - Proper error handling
    """
    try:
        # Create document record in DB
        document = await create_document_record(
            db=db,
            file_name=request.file_name,
            source=request.source,
            user_id=user.id
        )
        await db.commit()
        
        # Schedule indexing as background task
        background_tasks.add_task(
            index_document_async,
            document_id=document.id,
            content=request.content,
            metadata=request.metadata
        )
        
        return DocumentResponse(
            id=document.id,
            file_name=document.file_name,
            source=document.source,
            indexed_at=document.created_at,
            chunk_count=0,  # Will be updated by background task
            status="indexing"
        )
        
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to upload document: {e}")
        raise HTTPException(status_code=500, detail="Failed to upload document")
```

### Database Operations with Async SQLAlchemy

```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

async def get_document_with_chunks(
    db: AsyncSession,
    document_id: str,
    user_id: str
) -> Optional[Document]:
    """
    Fetch document with eager loading.
    
    Onyx pattern:
    - Use select() for queries
    - selectinload() for relationships
    - Filter by user permissions
    """
    stmt = (
        select(Document)
        .options(selectinload(Document.chunks))
        .where(
            Document.id == document_id,
            Document.user_id == user_id
        )
    )
    
    result = await db.execute(stmt)
    return result.scalar_one_or_none()

async def search_documents(
    db: AsyncSession,
    query: str,
    user_id: str,
    limit: int = 10
) -> List[Document]:
    """
    Search documents with filtering.
    
    Use async iteration for large result sets.
    """
    stmt = (
        select(Document)
        .where(
            Document.user_id == user_id,
            Document.content.ilike(f"%{query}%")
        )
        .limit(limit)
    )
    
    result = await db.execute(stmt)
    return result.scalars().all()
```

### Concurrent Operations

```python
import asyncio
from typing import List

async def process_multiple_documents(
    document_ids: List[str],
    db: AsyncSession
) -> List[ProcessingResult]:
    """
    Process multiple documents concurrently.
    
    Onyx pattern: Use asyncio.gather for parallelism
    """
    tasks = [
        process_single_document(doc_id, db)
        for doc_id in document_ids
    ]
    
    # gather with return_exceptions to handle partial failures
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Process results
    processed = []
    for doc_id, result in zip(document_ids, results):
        if isinstance(result, Exception):
            logger.error(f"Failed to process {doc_id}: {result}")
            processed.append(ProcessingResult(doc_id=doc_id, success=False))
        else:
            processed.append(result)
    
    return processed
```

## Authentication and Authorization

### Dependency Injection for Auth

```python
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError

from onyx.configs.app_configs import SECRET_KEY
from onyx.auth.schemas import User

security = HTTPBearer()

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_async_session)
) -> User:
    """
    Extract and validate user from JWT token.
    
    Onyx auth pattern:
    - JWT tokens in Authorization header
    - Token validation
    - User lookup from database
    """
    token = credentials.credentials
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        user_id: str = payload.get("sub")
        
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials"
            )
            
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )
    
    # Fetch user from database
    user = await get_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )
    
    return user

async def get_admin_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """
    Require admin role.
    
    Chain dependencies for role-based access.
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user

# Usage in routes
@router.delete("/documents/{document_id}")
async def delete_document(
    document_id: str,
    db: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_current_user)  # Requires authentication
):
    """Delete a document. Only owner or admin can delete."""
    document = await get_document(db, document_id)
    
    if document.user_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    await db.delete(document)
    await db.commit()
    
    return {"message": "Document deleted"}
```

### Session Management

```python
from fastapi import Cookie, Response
from datetime import datetime, timedelta

async def create_session(
    response: Response,
    user_id: str,
    db: AsyncSession
) -> str:
    """
    Create user session with cookie.
    
    Onyx session pattern:
    - HTTP-only cookies
    - Session stored in database
    - Configurable expiration
    """
    session_token = generate_secure_token()
    expires_at = datetime.utcnow() + timedelta(days=7)
    
    # Store session in database
    session = UserSession(
        token=session_token,
        user_id=user_id,
        expires_at=expires_at
    )
    db.add(session)
    await db.commit()
    
    # Set cookie
    response.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        secure=True,  # HTTPS only in production
        samesite="lax",
        max_age=7 * 24 * 60 * 60  # 7 days
    )
    
    return session_token

async def get_user_from_session(
    session_token: str = Cookie(None),
    db: AsyncSession = Depends(get_async_session)
) -> Optional[User]:
    """Get user from session cookie."""
    if not session_token:
        return None
    
    session = await get_session(db, session_token)
    if not session or session.expires_at < datetime.utcnow():
        return None
    
    return await get_user_by_id(db, session.user_id)
```

## Error Handling

### Custom Exception Handlers

```python
from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

class DocumentNotFoundError(Exception):
    """Custom exception for missing documents."""
    def __init__(self, document_id: str):
        self.document_id = document_id
        super().__init__(f"Document {document_id} not found")

class InsufficientPermissionsError(Exception):
    """Custom exception for permission errors."""
    def __init__(self, resource: str, action: str):
        self.resource = resource
        self.action = action
        super().__init__(f"Insufficient permissions to {action} {resource}")

@app.exception_handler(DocumentNotFoundError)
async def document_not_found_handler(
    request: Request,
    exc: DocumentNotFoundError
):
    """Handle document not found errors."""
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={
            "error": "document_not_found",
            "message": str(exc),
            "document_id": exc.document_id
        }
    )

@app.exception_handler(InsufficientPermissionsError)
async def permission_error_handler(
    request: Request,
    exc: InsufficientPermissionsError
):
    """Handle permission errors."""
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content={
            "error": "insufficient_permissions",
            "message": str(exc),
            "resource": exc.resource,
            "action": exc.action
        }
    )

@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request,
    exc: RequestValidationError
):
    """
    Handle Pydantic validation errors.
    
    Onyx pattern: Return structured error details.
    """
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": "validation_error",
            "message": "Request validation failed",
            "details": exc.errors()
        }
    )
```

### Error Response Patterns

```python
from typing import Optional
from pydantic import BaseModel

class ErrorResponse(BaseModel):
    """Standardized error response."""
    error: str = Field(..., description="Error code")
    message: str = Field(..., description="Human-readable message")
    details: Optional[dict] = Field(None, description="Additional error details")
    request_id: Optional[str] = Field(None, description="Request ID for tracking")

def create_error_response(
    error_code: str,
    message: str,
    details: Optional[dict] = None,
    request: Optional[Request] = None
) -> ErrorResponse:
    """
    Create standardized error response.
    
    Onyx pattern: Consistent error structure.
    """
    request_id = None
    if request:
        request_id = request.headers.get("X-Request-ID")
    
    return ErrorResponse(
        error=error_code,
        message=message,
        details=details,
        request_id=request_id
    )
```

## Response Streaming

### Streaming Chat Responses

```python
from fastapi.responses import StreamingResponse
from typing import AsyncGenerator
import json

async def stream_chat_response(
    message: str,
    conversation_id: str
) -> AsyncGenerator[str, None]:
    """
    Stream LLM response tokens.
    
    Onyx streaming pattern:
    - Server-Sent Events (SSE)
    - JSON-encoded chunks
    - Proper error handling in stream
    """
    try:
        # Get LLM client
        llm = get_llm_client()
        
        # Stream tokens
        async for token in llm.stream_chat(message, conversation_id):
            chunk = {
                "type": "token",
                "content": token,
                "conversation_id": conversation_id
            }
            yield f"data: {json.dumps(chunk)}\n\n"
        
        # Send completion signal
        completion = {
            "type": "done",
            "conversation_id": conversation_id
        }
        yield f"data: {json.dumps(completion)}\n\n"
        
    except Exception as e:
        error = {
            "type": "error",
            "message": str(e)
        }
        yield f"data: {json.dumps(error)}\n\n"

@router.post("/chat/stream")
async def stream_chat(
    request: ChatRequest,
    user: User = Depends(get_current_user)
):
    """Stream chat response to client."""
    return StreamingResponse(
        stream_chat_response(request.message, request.conversation_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Disable nginx buffering
        }
    )
```

## Background Tasks

### Background Task Patterns

```python
from fastapi import BackgroundTasks

async def index_document_background(
    document_id: str,
    content: str
):
    """
    Background task for document indexing.
    
    Onyx pattern:
    - Long-running operations as background tasks
    - Update database status
    - Handle errors gracefully
    """
    try:
        # Update status to indexing
        async with get_async_session_context() as db:
            await update_document_status(db, document_id, "indexing")
            await db.commit()
        
        # Perform indexing
        await index_document(document_id, content)
        
        # Update status to completed
        async with get_async_session_context() as db:
            await update_document_status(db, document_id, "completed")
            await db.commit()
            
    except Exception as e:
        logger.error(f"Indexing failed for {document_id}: {e}")
        async with get_async_session_context() as db:
            await update_document_status(db, document_id, "failed")
            await db.commit()

@router.post("/documents/batch")
async def upload_documents_batch(
    documents: List[DocumentUploadRequest],
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user)
):
    """
    Upload multiple documents with background indexing.
    
    FastAPI automatically handles background task execution.
    """
    document_ids = []
    
    for doc_request in documents:
        doc_id = generate_document_id()
        document_ids.append(doc_id)
        
        # Schedule background task
        background_tasks.add_task(
            index_document_background,
            doc_id,
            doc_request.content
        )
    
    return {
        "message": f"Queued {len(documents)} documents for indexing",
        "document_ids": document_ids
    }
```

## Rate Limiting

### Rate Limiting Middleware

```python
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    """Handle rate limit errors."""
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={
            "error": "rate_limit_exceeded",
            "message": "Too many requests. Please try again later.",
            "retry_after": exc.retry_after if hasattr(exc, 'retry_after') else None
        }
    )

# Apply rate limits to routes
@router.post("/query")
@limiter.limit("10/minute")  # 10 requests per minute
async def query_documents(
    request: Request,
    query: SearchRequest,
    user: User = Depends(get_current_user)
):
    """Search documents with rate limiting."""
    results = await search(query.query, user.id)
    return SearchResponse(results=results)
```

## Testing

### Testing FastAPI Endpoints

```python
from fastapi.testclient import TestClient
import pytest
from httpx import AsyncClient

# Synchronous testing
def test_upload_document():
    """Test document upload endpoint."""
    client = TestClient(app)
    
    response = client.post(
        "/api/documents",
        json={
            "file_name": "test.pdf",
            "content": "Test content",
            "source": "local"
        },
        headers={"Authorization": "Bearer test_token"}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert data["status"] == "indexing"

# Async testing
@pytest.mark.asyncio
async def test_search_async():
    """Test search endpoint with async client."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.post(
            "/api/query",
            json={"query": "test query"},
            headers={"Authorization": "Bearer test_token"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "results" in data

# Test with mocked dependencies
@pytest.mark.asyncio
async def test_with_mocked_db():
    """Test with mocked database."""
    from unittest.mock import AsyncMock
    
    async def override_get_db():
        return AsyncMock()
    
    app.dependency_overrides[get_async_session] = override_get_db
    
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/api/documents")
        assert response.status_code == 200
```

## Common Patterns and Anti-Patterns

### ✅ DO: Use Type Hints Everywhere

```python
from typing import List, Optional

async def get_documents(
    db: AsyncSession,
    user_id: str,
    limit: int = 10
) -> List[Document]:
    """Type hints enable IDE support and validation."""
    pass
```

### ❌ DON'T: Block the Event Loop

```python
# Bad: Blocking I/O
@router.get("/documents")
async def get_documents():
    time.sleep(5)  # Blocks entire server!
    return documents

# Good: Use async
@router.get("/documents")
async def get_documents():
    await asyncio.sleep(5)  # Doesn't block
    return documents
```

### ✅ DO: Use Dependencies for Reusable Logic

```python
# Good: Dependency for common checks
async def verify_document_access(
    document_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
) -> Document:
    """Verify user can access document."""
    doc = await get_document(db, document_id)
    if doc.user_id != user.id:
        raise HTTPException(403)
    return doc

@router.get("/documents/{document_id}")
async def get_document(
    document: Document = Depends(verify_document_access)
):
    return document
```

## Performance Tips

1. **Use async everywhere for I/O**: Database, HTTP requests, file operations
2. **Enable response compression**: GZip middleware for large responses
3. **Implement caching**: Use Redis for frequently accessed data
4. **Optimize database queries**: Use eager loading, indexes
5. **Profile slow endpoints**: Use middleware to track response times
6. **Use connection pooling**: Configure SQLAlchemy pool settings

## Additional Resources

- FastAPI documentation: https://fastapi.tiangolo.com
- Pydantic models: https://docs.pydantic.dev
- SQLAlchemy async: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
- Onyx repository: https://github.com/onyx-dot-app/onyx
