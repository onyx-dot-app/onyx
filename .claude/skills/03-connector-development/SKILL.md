---
name: connector-development
description: Patterns for building connectors to external services (Google Drive, Slack, Confluence, etc.) with OAuth2, webhooks, rate limiting, and incremental sync. Use when creating new connectors or modifying existing integrations.
---

# Connector Development Skill for Onyx

## Overview

Onyx connectors integrate with 40+ external services to pull documents, metadata, and access permissions. This skill covers the patterns for building reliable, performant connectors that handle authentication, rate limiting, incremental syncs, and permission mirroring.

## Architecture Context

**Connector System:**
- **Location**: `backend/danswer/connectors/`
- **Base Class**: `BaseConnector` and `LoadConnector` interfaces
- **Execution**: Background workers poll and sync connectors
- **Storage**: Credentials encrypted in PostgreSQL
- **State Management**: Track sync progress, last run times

**Key Connector Types:**
- **File Storage**: Google Drive, Dropbox, SharePoint
- **Communication**: Slack, Microsoft Teams, Gmail
- **Documentation**: Confluence, Notion, GitBook
- **Development**: GitHub, GitLab, Jira
- **CRM**: Salesforce, HubSpot

## Base Connector Interface

### Connector Abstract Base Class

```python
from abc import ABC, abstractmethod
from typing import Any, Iterator, Optional
from datetime import datetime
from pydantic import BaseModel

class DocumentMetadata(BaseModel):
    """Standard metadata for all documents."""
    source: str
    source_id: str
    title: str
    created_at: datetime
    updated_at: datetime
    author: Optional[str] = None
    url: Optional[str] = None
    permissions: list[str] = []  # User IDs/emails with access

class ConnectorDocument(BaseModel):
    """Document returned by connector."""
    id: str
    content: str
    metadata: DocumentMetadata
    semantic_id: str  # Stable ID for deduplication

class BaseConnector(ABC):
    """
    Base class for all Onyx connectors.
    
    Onyx connector pattern:
    - Iterators for memory efficiency
    - Incremental sync support
    - Permission mirroring
    - Error handling and retry logic
    """
    
    def __init__(self, credentials: dict[str, Any]):
        """Initialize connector with credentials."""
        self.credentials = credentials
        self._validate_credentials()
    
    @abstractmethod
    def _validate_credentials(self) -> None:
        """Validate credentials are complete."""
        pass
    
    @abstractmethod
    def load_documents(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> Iterator[ConnectorDocument]:
        """
        Load documents from source.
        
        Args:
            start_time: Only fetch docs updated after this time (incremental)
            end_time: Only fetch docs updated before this time
            
        Yields:
            ConnectorDocument objects
        """
        pass
    
    @abstractmethod
    def test_connection(self) -> dict[str, Any]:
        """
        Test connection to external service.
        
        Returns:
            Dict with status and any diagnostic info
        """
        pass
    
    def get_rate_limit_status(self) -> dict[str, Any]:
        """Return rate limit info if available."""
        return {"rate_limits": "unknown"}
```

## OAuth2 Implementation

### OAuth2 Flow for Connectors

```python
from fastapi import HTTPException
import httpx
from typing import Optional
from urllib.parse import urlencode

class OAuth2Connector(BaseConnector):
    """
    Base class for OAuth2-based connectors.
    
    Onyx OAuth pattern:
    - Handle token refresh automatically
    - Store tokens encrypted
    - Provide auth URL generation
    """
    
    CLIENT_ID: str = ""
    CLIENT_SECRET: str = ""
    AUTH_URL: str = ""
    TOKEN_URL: str = ""
    SCOPES: list[str] = []
    
    def __init__(self, credentials: dict[str, Any]):
        """
        Initialize OAuth2 connector.
        
        credentials should contain:
        - access_token
        - refresh_token (optional)
        - expires_at (optional)
        """
        super().__init__(credentials)
        self.access_token = credentials.get("access_token")
        self.refresh_token = credentials.get("refresh_token")
        self.expires_at = credentials.get("expires_at")
    
    def _validate_credentials(self) -> None:
        """Validate OAuth credentials."""
        if not self.access_token:
            raise ValueError("access_token required for OAuth2 connector")
    
    @classmethod
    def get_authorization_url(cls, state: str, redirect_uri: str) -> str:
        """
        Generate OAuth2 authorization URL.
        
        Called when user initiates connector setup.
        """
        params = {
            "client_id": cls.CLIENT_ID,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(cls.SCOPES),
            "state": state,
            "access_type": "offline",  # Request refresh token
            "prompt": "consent"
        }
        return f"{cls.AUTH_URL}?{urlencode(params)}"
    
    @classmethod
    async def exchange_code_for_token(
        cls,
        code: str,
        redirect_uri: str
    ) -> dict[str, Any]:
        """
        Exchange authorization code for tokens.
        
        Called after user authorizes the connector.
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                cls.TOKEN_URL,
                data={
                    "client_id": cls.CLIENT_ID,
                    "client_secret": cls.CLIENT_SECRET,
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code"
                }
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=400,
                    detail=f"Token exchange failed: {response.text}"
                )
            
            return response.json()
    
    async def refresh_access_token(self) -> str:
        """
        Refresh access token using refresh token.
        
        Onyx pattern: Auto-refresh before making API calls.
        """
        if not self.refresh_token:
            raise ValueError("No refresh token available")
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.TOKEN_URL,
                data={
                    "client_id": self.CLIENT_ID,
                    "client_secret": self.CLIENT_SECRET,
                    "refresh_token": self.refresh_token,
                    "grant_type": "refresh_token"
                }
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=401,
                    detail="Failed to refresh token"
                )
            
            token_data = response.json()
            self.access_token = token_data["access_token"]
            
            # Update stored credentials
            await self._update_stored_credentials({
                "access_token": self.access_token,
                "expires_at": token_data.get("expires_in")
            })
            
            return self.access_token
    
    async def _make_authenticated_request(
        self,
        method: str,
        url: str,
        **kwargs
    ) -> httpx.Response:
        """
        Make authenticated API request with auto-refresh.
        
        Handles token refresh if needed.
        """
        # Check if token needs refresh
        if self.expires_at and datetime.utcnow() >= self.expires_at:
            await self.refresh_access_token()
        
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self.access_token}"
        
        async with httpx.AsyncClient() as client:
            response = await client.request(
                method,
                url,
                headers=headers,
                **kwargs
            )
            
            # Handle token expiration
            if response.status_code == 401:
                await self.refresh_access_token()
                headers["Authorization"] = f"Bearer {self.access_token}"
                response = await client.request(
                    method,
                    url,
                    headers=headers,
                    **kwargs
                )
            
            return response
```

### Example: Google Drive Connector

```python
class GoogleDriveConnector(OAuth2Connector):
    """
    Google Drive connector implementation.
    
    Features:
    - Incremental sync
    - Permission mirroring
    - File type filtering
    - Shared drive support
    """
    
    CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
    CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
    AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    SCOPES = [
        "https://www.googleapis.com/auth/drive.readonly",
        "https://www.googleapis.com/auth/drive.metadata.readonly"
    ]
    
    API_BASE = "https://www.googleapis.com/drive/v3"
    
    SUPPORTED_MIME_TYPES = [
        "application/vnd.google-apps.document",
        "application/vnd.google-apps.presentation",
        "application/vnd.google-apps.spreadsheet",
        "application/pdf",
        "text/plain"
    ]
    
    async def load_documents(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> Iterator[ConnectorDocument]:
        """
        Load documents from Google Drive.
        
        Onyx pattern:
        - Paginate through all files
        - Filter by modification time for incremental sync
        - Export Google Docs to text format
        - Fetch permissions for each file
        """
        page_token = None
        
        while True:
            # Build query
            query_parts = [
                f"mimeType in ({','.join(repr(t) for t in self.SUPPORTED_MIME_TYPES)})",
                "trashed = false"
            ]
            
            if start_time:
                query_parts.append(
                    f"modifiedTime > '{start_time.isoformat()}'"
                )
            
            query = " and ".join(query_parts)
            
            # Fetch files
            params = {
                "q": query,
                "fields": "nextPageToken, files(id, name, mimeType, modifiedTime, createdTime, owners, webViewLink, permissions)",
                "pageSize": 100,
                "supportsAllDrives": True,
                "includeItemsFromAllDrives": True
            }
            
            if page_token:
                params["pageToken"] = page_token
            
            response = await self._make_authenticated_request(
                "GET",
                f"{self.API_BASE}/files",
                params=params
            )
            
            data = response.json()
            files = data.get("files", [])
            
            for file in files:
                try:
                    # Get file content
                    content = await self._get_file_content(file)
                    
                    # Extract permissions
                    permissions = self._extract_permissions(file)
                    
                    yield ConnectorDocument(
                        id=file["id"],
                        content=content,
                        metadata=DocumentMetadata(
                            source="google_drive",
                            source_id=file["id"],
                            title=file["name"],
                            created_at=datetime.fromisoformat(
                                file["createdTime"].rstrip("Z")
                            ),
                            updated_at=datetime.fromisoformat(
                                file["modifiedTime"].rstrip("Z")
                            ),
                            author=file.get("owners", [{}])[0].get("emailAddress"),
                            url=file.get("webViewLink"),
                            permissions=permissions
                        ),
                        semantic_id=f"google_drive:{file['id']}"
                    )
                    
                except Exception as e:
                    logger.error(f"Failed to process file {file['id']}: {e}")
                    continue
            
            # Check for more pages
            page_token = data.get("nextPageToken")
            if not page_token:
                break
    
    async def _get_file_content(self, file: dict) -> str:
        """
        Get file content.
        
        Handle different file types:
        - Google Docs: Export as text
        - PDFs: Download binary
        - Text files: Download directly
        """
        mime_type = file["mimeType"]
        file_id = file["id"]
        
        # Google Workspace files need to be exported
        if mime_type.startswith("application/vnd.google-apps"):
            export_mime = self._get_export_mime_type(mime_type)
            response = await self._make_authenticated_request(
                "GET",
                f"{self.API_BASE}/files/{file_id}/export",
                params={"mimeType": export_mime}
            )
            return response.text
        
        # Regular files
        response = await self._make_authenticated_request(
            "GET",
            f"{self.API_BASE}/files/{file_id}",
            params={"alt": "media"}
        )
        
        # Handle binary files
        if mime_type == "application/pdf":
            return self._extract_pdf_text(response.content)
        
        return response.text
    
    def _extract_permissions(self, file: dict) -> list[str]:
        """
        Extract user emails who have access to file.
        
        Onyx permission mirroring:
        - Map Drive permissions to user emails
        - Handle domain-wide sharing
        - Track inherited permissions
        """
        permissions = []
        
        for perm in file.get("permissions", []):
            if perm.get("type") == "user":
                email = perm.get("emailAddress")
                if email:
                    permissions.append(email)
            elif perm.get("type") == "domain":
                # Domain-wide access - could map to all users in org
                domain = perm.get("domain")
                permissions.append(f"domain:{domain}")
        
        return permissions
    
    async def test_connection(self) -> dict[str, Any]:
        """Test Google Drive API connection."""
        try:
            response = await self._make_authenticated_request(
                "GET",
                f"{self.API_BASE}/about",
                params={"fields": "user"}
            )
            
            if response.status_code == 200:
                user = response.json().get("user", {})
                return {
                    "status": "success",
                    "user_email": user.get("emailAddress"),
                    "display_name": user.get("displayName")
                }
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e)
            }
```

## Rate Limiting and Retry Logic

### Rate Limit Handler

```python
import asyncio
from typing import Callable, Any
import httpx

class RateLimiter:
    """
    Handle API rate limits with exponential backoff.
    
    Onyx rate limiting pattern:
    - Respect rate limit headers
    - Exponential backoff on 429s
    - Per-connector rate limit tracking
    """
    
    def __init__(
        self,
        max_retries: int = 5,
        base_delay: float = 1.0,
        max_delay: float = 60.0
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.rate_limit_resets = {}
    
    async def execute_with_retry(
        self,
        func: Callable,
        *args,
        **kwargs
    ) -> Any:
        """Execute function with automatic retry on rate limits."""
        last_exception = None
        
        for attempt in range(self.max_retries):
            try:
                result = await func(*args, **kwargs)
                
                # If it's an HTTP response, check rate limits
                if isinstance(result, httpx.Response):
                    self._update_rate_limits(result)
                    
                    if result.status_code == 429:
                        # Rate limited
                        retry_after = self._get_retry_after(result)
                        await asyncio.sleep(retry_after)
                        continue
                    
                    result.raise_for_status()
                
                return result
                
            except httpx.HTTPStatusError as e:
                last_exception = e
                
                if e.response.status_code == 429:
                    # Rate limited
                    retry_after = self._get_retry_after(e.response)
                    logger.warning(
                        f"Rate limited, retry after {retry_after}s (attempt {attempt + 1})"
                    )
                    await asyncio.sleep(retry_after)
                    continue
                
                elif e.response.status_code >= 500:
                    # Server error - retry with backoff
                    delay = min(
                        self.base_delay * (2 ** attempt),
                        self.max_delay
                    )
                    logger.warning(
                        f"Server error {e.response.status_code}, retry in {delay}s"
                    )
                    await asyncio.sleep(delay)
                    continue
                
                else:
                    # Client error - don't retry
                    raise
            
            except Exception as e:
                last_exception = e
                delay = min(
                    self.base_delay * (2 ** attempt),
                    self.max_delay
                )
                logger.error(f"Error in attempt {attempt + 1}: {e}")
                await asyncio.sleep(delay)
        
        raise last_exception or Exception("Max retries exceeded")
    
    def _get_retry_after(self, response: httpx.Response) -> float:
        """Extract retry-after from response headers."""
        retry_after = response.headers.get("Retry-After")
        
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                # Retry-After might be a date
                pass
        
        # Default exponential backoff
        return self.base_delay
    
    def _update_rate_limits(self, response: httpx.Response):
        """Track rate limit info from headers."""
        limit = response.headers.get("X-RateLimit-Limit")
        remaining = response.headers.get("X-RateLimit-Remaining")
        reset = response.headers.get("X-RateLimit-Reset")
        
        if all([limit, remaining, reset]):
            self.rate_limit_resets[response.url.host] = {
                "limit": int(limit),
                "remaining": int(remaining),
                "reset": int(reset)
            }
```

## Webhook Support

### Webhook Handler for Real-time Updates

```python
from fastapi import APIRouter, Request, HTTPException
import hmac
import hashlib

class WebhookConnector(BaseConnector):
    """
    Base class for connectors with webhook support.
    
    Webhooks enable real-time updates instead of polling.
    """
    
    WEBHOOK_SECRET: str = ""
    
    @classmethod
    def create_webhook_router(cls) -> APIRouter:
        """Create FastAPI router for webhook endpoints."""
        router = APIRouter()
        
        @router.post("/webhooks/{connector_id}")
        async def handle_webhook(
            connector_id: str,
            request: Request
        ):
            """Handle incoming webhook."""
            # Verify webhook signature
            if not cls._verify_webhook_signature(request):
                raise HTTPException(status_code=401, detail="Invalid signature")
            
            # Parse webhook payload
            payload = await request.json()
            
            # Queue document for reindexing
            await cls._process_webhook_event(connector_id, payload)
            
            return {"status": "ok"}
        
        return router
    
    @classmethod
    def _verify_webhook_signature(cls, request: Request) -> bool:
        """
        Verify webhook signature.
        
        Different services use different signature methods:
        - Slack: X-Slack-Signature with HMAC
        - GitHub: X-Hub-Signature-256
        - Generic: X-Webhook-Signature
        """
        signature_header = request.headers.get("X-Webhook-Signature")
        if not signature_header:
            return False
        
        body = request.body()
        expected_signature = hmac.new(
            cls.WEBHOOK_SECRET.encode(),
            body,
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(signature_header, expected_signature)
    
    @classmethod
    async def _process_webhook_event(
        cls,
        connector_id: str,
        payload: dict
    ):
        """
        Process webhook event.
        
        Onyx pattern:
        - Parse event type
        - Extract document ID
        - Queue for reindexing
        """
        event_type = payload.get("type")
        
        if event_type in ["file.created", "file.updated"]:
            document_id = payload.get("file_id")
            # Queue document for incremental update
            await queue_document_sync(connector_id, document_id)
        
        elif event_type == "file.deleted":
            document_id = payload.get("file_id")
            # Remove from index
            await remove_document_from_index(document_id)

# Example: Slack Webhook Connector
class SlackConnector(WebhookConnector, OAuth2Connector):
    """Slack connector with webhook support."""
    
    WEBHOOK_SECRET = os.getenv("SLACK_WEBHOOK_SECRET")
    
    async def subscribe_to_webhooks(self) -> dict[str, Any]:
        """
        Subscribe to Slack events.
        
        Called during connector setup.
        """
        webhook_url = f"{get_base_url()}/webhooks/{self.connector_id}"
        
        response = await self._make_authenticated_request(
            "POST",
            "https://slack.com/api/apps.event.subscriptions.enable",
            json={
                "url": webhook_url,
                "events": [
                    "message.channels",
                    "message.groups",
                    "file_shared"
                ]
            }
        )
        
        return response.json()
```

## Incremental Sync Strategies

### Sync State Management

```python
from datetime import datetime, timedelta
from typing import Optional

class SyncState(BaseModel):
    """Track connector sync state."""
    connector_id: str
    last_successful_sync: Optional[datetime] = None
    last_sync_cursor: Optional[str] = None  # For cursor-based pagination
    documents_synced: int = 0
    documents_failed: int = 0

async def perform_incremental_sync(
    connector: BaseConnector,
    connector_id: str,
    db: AsyncSession
) -> SyncState:
    """
    Perform incremental sync for connector.
    
    Onyx sync pattern:
    1. Load last sync state
    2. Fetch documents modified since last sync
    3. Update or insert documents
    4. Update sync state
    """
    # Load last sync state
    sync_state = await get_sync_state(db, connector_id)
    
    start_time = sync_state.last_successful_sync
    if start_time:
        # Add buffer to handle clock skew
        start_time = start_time - timedelta(minutes=5)
    
    documents_synced = 0
    documents_failed = 0
    
    try:
        # Fetch documents
        async for document in connector.load_documents(start_time=start_time):
            try:
                # Upsert document
                await upsert_document(db, document)
                documents_synced += 1
                
                # Commit in batches
                if documents_synced % 100 == 0:
                    await db.commit()
                    
            except Exception as e:
                logger.error(f"Failed to sync document {document.id}: {e}")
                documents_failed += 1
        
        await db.commit()
        
        # Update sync state
        sync_state.last_successful_sync = datetime.utcnow()
        sync_state.documents_synced = documents_synced
        sync_state.documents_failed = documents_failed
        await update_sync_state(db, sync_state)
        await db.commit()
        
    except Exception as e:
        logger.error(f"Sync failed for connector {connector_id}: {e}")
        await db.rollback()
        raise
    
    return sync_state
```

## Testing Connectors

### Connector Test Suite

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_google_drive_connector():
    """Test Google Drive connector."""
    # Mock credentials
    credentials = {
        "access_token": "test_token",
        "refresh_token": "refresh_token"
    }
    
    connector = GoogleDriveConnector(credentials)
    
    # Mock API responses
    with patch.object(
        connector,
        "_make_authenticated_request",
        new=AsyncMock()
    ) as mock_request:
        mock_request.return_value.json.return_value = {
            "files": [
                {
                    "id": "file123",
                    "name": "Test Document",
                    "mimeType": "application/vnd.google-apps.document",
                    "modifiedTime": "2024-01-01T00:00:00Z",
                    "createdTime": "2024-01-01T00:00:00Z"
                }
            ]
        }
        
        # Test document loading
        documents = []
        async for doc in connector.load_documents():
            documents.append(doc)
        
        assert len(documents) == 1
        assert documents[0].id == "file123"
        assert documents[0].metadata.title == "Test Document"

@pytest.mark.asyncio
async def test_rate_limiting():
    """Test rate limiter handles 429 responses."""
    rate_limiter = RateLimiter(max_retries=3)
    
    call_count = 0
    
    async def mock_api_call():
        nonlocal call_count
        call_count += 1
        
        if call_count < 3:
            # Simulate rate limit
            response = MagicMock()
            response.status_code = 429
            response.headers = {"Retry-After": "1"}
            raise httpx.HTTPStatusError("Rate limited", request=None, response=response)
        
        return "success"
    
    result = await rate_limiter.execute_with_retry(mock_api_call)
    
    assert result == "success"
    assert call_count == 3
```

## Common Patterns

### ✅ DO: Implement Incremental Sync

```python
# Good: Only fetch new/modified documents
async def load_documents(self, start_time: Optional[datetime] = None):
    if start_time:
        query = f"modifiedTime > '{start_time.isoformat()}'"
    else:
        query = "trashed = false"  # Full sync
```

### ✅ DO: Mirror Permissions

```python
# Good: Track document permissions for access control
metadata=DocumentMetadata(
    permissions=["user1@company.com", "user2@company.com"]
)
```

### ❌ DON'T: Ignore Rate Limits

```python
# Bad: No rate limiting
for page in range(1000):
    response = await api_call()  # Will get rate limited!

# Good: Use rate limiter
async for page in paginate_with_rate_limiting():
    response = await api_call()
```

## Additional Resources

- OAuth 2.0 spec: https://oauth.net/2/
- Webhook security: https://webhooks.fyi
- Onyx connector examples: https://github.com/onyx-dot-app/onyx/tree/main/backend/danswer/connectors
