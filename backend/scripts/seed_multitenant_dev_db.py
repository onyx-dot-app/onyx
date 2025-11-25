#!/usr/bin/env python3
"""
Script to populate a multi-tenant dev database with realistic test data.

Usage:
    PYTHONPATH=. python scripts/seed_multitenant_dev_db.py --tenants 5 --sessions-per-tenant 100

This script will:
1. Create multiple tenants (by creating admin users for each)
2. Seed chat history for each tenant
3. Seed documents with realistic metadata for each tenant
4. Create connectors and credentials
5. Optionally create LLM providers and personas

Requirements:
- Multi-tenant dev environment must be running (docker-compose.multitenant-dev.yml)
- API server must be accessible at the configured host/port
"""

import argparse
import logging
import random
import sys
import time
from datetime import datetime
from datetime import timedelta
from typing import Optional
from uuid import uuid4

import requests

from onyx.access.models import DocumentAccess
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import MessageType
from onyx.connectors.models import Document
from onyx.db.chat import create_chat_session
from onyx.db.chat import create_new_chat_message
from onyx.db.chat import get_or_create_root_message
from onyx.db.engine.sql_engine import get_session_with_shared_schema
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.models import ChatSession
from onyx.db.models import UserTenantMapping
from onyx.db.search_settings import get_current_search_settings
from onyx.document_index.document_index_utils import get_multipass_config
from onyx.document_index.vespa.index import VespaIndex
from onyx.indexing.indexing_pipeline import IndexBatchParams
from onyx.indexing.models import ChunkEmbedding
from onyx.indexing.models import DocMetadataAwareIndexChunk
from onyx.indexing.models import IndexChunk
from onyx.utils.logger import setup_logger
from shared_configs.model_server_models import Embedding

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = setup_logger()

# Constants
API_SERVER_PROTOCOL = "http"
API_SERVER_HOST = "127.0.0.1"
API_SERVER_PORT = "8080"
API_SERVER_URL = f"{API_SERVER_PROTOCOL}://{API_SERVER_HOST}:{API_SERVER_PORT}"
GENERAL_HEADERS = {"Content-Type": "application/json"}
DEFAULT_PASSWORD = "TestPassword123!"

# Sample company names for realistic tenants
SAMPLE_COMPANIES = [
    "Acme Corp",
    "TechStart Inc",
    "Global Solutions",
    "Innovation Labs",
    "Digital Ventures",
    "Cloud Systems",
    "Data Dynamics",
    "Smart Analytics",
    "Future Tech",
    "Enterprise Solutions",
]

# Sample chat queries for realistic history
SAMPLE_QUERIES = [
    "What is our company policy on remote work?",
    "Can you summarize the Q3 financial results?",
    "How do I submit a vacation request?",
    "What are the benefits of our health insurance plan?",
    "Who is responsible for IT support?",
    "What are the upcoming company events?",
    "Can you explain the new project management tool?",
    "What is the process for submitting expenses?",
    "How do I access the employee handbook?",
    "What training programs are available?",
    "Can you help me find the marketing guidelines?",
    "What is our sustainability initiative?",
    "How do I schedule a meeting room?",
    "What are the security protocols for data handling?",
    "Can you provide information about career development?",
]

SAMPLE_ASSISTANT_RESPONSES = [
    "Based on the company policies, here's what I found...",
    "According to the latest documentation, the answer is...",
    "Let me help you with that. Here's the relevant information...",
    "I found several documents related to your question...",
    "The policy states that...",
    "Here's a summary of what I found in our knowledge base...",
    "According to the employee handbook...",
    "I can help you with that. The process involves...",
    "Based on recent updates to our procedures...",
    "Let me search through our documents for that information...",
]


class TenantData:
    """Holds data for a created tenant."""

    def __init__(
        self,
        tenant_id: str,
        admin_user_id: str,
        admin_email: str,
        admin_password: str,
        company_name: str,
        headers: dict,
        cookies: dict,
    ):
        self.tenant_id = tenant_id
        self.admin_user_id = admin_user_id
        self.admin_email = admin_email
        self.admin_password = admin_password
        self.company_name = company_name
        self.headers = headers
        self.cookies = cookies


def create_tenant(company_name: str, api_url: str) -> Optional[TenantData]:
    """Create a new tenant by registering an admin user."""
    unique = uuid4().hex[:8]
    email = f"admin_{unique}@{company_name.lower().replace(' ', '')}.com"
    password = DEFAULT_PASSWORD

    logger.info(f"Creating tenant for {company_name} with admin email: {email}")

    body = {
        "email": email,
        "username": email,
        "password": password,
    }

    try:
        # Register user
        response = requests.post(
            url=f"{api_url}/auth/register",
            json=body,
            headers=GENERAL_HEADERS,
            timeout=30,
        )
        response.raise_for_status()
        user_id = response.json()["id"]

        # Login to get session
        from urllib.parse import urlencode

        data = urlencode({"username": email, "password": password})
        headers = GENERAL_HEADERS.copy()
        headers["Content-Type"] = "application/x-www-form-urlencoded"

        login_response = requests.post(
            url=f"{api_url}/auth/login",
            data=data,
            headers=headers,
            timeout=30,
        )
        login_response.raise_for_status()

        cookies = login_response.cookies.get_dict()
        session_cookie = cookies.get("fastapiusersauth")

        if not session_cookie:
            logger.error(f"Failed to get session cookie for {email}")
            return None

        # Prepare headers with auth
        auth_headers = GENERAL_HEADERS.copy()
        auth_headers["Cookie"] = f"fastapiusersauth={session_cookie}; "
        auth_cookies = {"fastapiusersauth": session_cookie}

        # Get tenant_id from the user_tenant_mapping table
        with get_session_with_shared_schema() as db_session:
            mapping = (
                db_session.query(UserTenantMapping)
                .filter(UserTenantMapping.email == email.lower())
                .first()
            )

            if not mapping:
                logger.error(f"No tenant mapping found for user {email}")
                return None

            tenant_id = mapping.tenant_id

        logger.info(f"✓ Created tenant {tenant_id} for {company_name} (admin: {email})")

        return TenantData(
            tenant_id=tenant_id,
            admin_user_id=user_id,
            admin_email=email,
            admin_password=password,
            company_name=company_name,
            headers=auth_headers,
            cookies=auth_cookies,
        )

    except Exception as e:
        logger.error(f"Failed to create tenant for {company_name}: {e}")
        return None


def seed_chat_history_for_tenant(
    tenant_id: str, num_sessions: int, num_messages: int, num_days: int
) -> None:
    """Seed chat history for a specific tenant."""
    logger.info(
        f"Seeding {num_sessions} chat sessions with {num_messages} messages each for tenant {tenant_id}"
    )

    with get_session_with_tenant(tenant_id=tenant_id) as db_session:
        # Create chat sessions
        for i in range(num_sessions):
            create_chat_session(
                db_session, f"test_session_{i}_{uuid4().hex[:8]}", None, None
            )

        db_session.commit()

        # Get all sessions and add messages
        rows = db_session.query(ChatSession).all()
        logger.info(f"Created {len(rows)} sessions, now adding messages...")

        for idx, row in enumerate(rows):
            if idx % 50 == 0 and idx > 0:
                logger.info(f"Seeded messages for {idx}/{len(rows)} sessions")

            # Randomize session timestamps
            row.time_created = datetime.utcnow() - timedelta(
                days=random.randint(0, num_days)
            )
            row.time_updated = row.time_created + timedelta(
                minutes=random.randint(0, 10)
            )

            root_message = get_or_create_root_message(row.id, db_session)

            current_message_type = MessageType.USER
            parent_message = root_message

            for msg_idx in range(num_messages):
                if current_message_type == MessageType.USER:
                    msg = random.choice(SAMPLE_QUERIES)
                else:
                    msg = random.choice(SAMPLE_ASSISTANT_RESPONSES)

                chat_message = create_new_chat_message(
                    chat_session_id=row.id,
                    parent_message=parent_message,
                    message=msg,
                    token_count=random.randint(50, 500),
                    message_type=current_message_type,
                    commit=False,
                    db_session=db_session,
                )

                chat_message.time_sent = row.time_created + timedelta(
                    minutes=msg_idx * 2
                )

                current_message_type = (
                    MessageType.ASSISTANT
                    if current_message_type == MessageType.USER
                    else MessageType.USER
                )
                parent_message = chat_message

            if idx % 50 == 0:
                db_session.commit()

        db_session.commit()
        logger.info(f"✓ Finished seeding chat history for tenant {tenant_id}")


def generate_random_embedding(dim: int) -> Embedding:
    """Generate a random embedding vector."""
    return [random.uniform(-1, 1) for _ in range(dim)]


def generate_dummy_chunk(
    doc_id: str,
    chunk_id: int,
    embedding_dim: int,
    tenant_id: str,
    company_name: str,
    number_of_acl_entries: int = 10,
    number_of_document_sets: int = 3,
) -> DocMetadataAwareIndexChunk:
    """Generate a dummy document chunk with realistic metadata."""
    # Generate realistic document content
    doc_types = ["Policy", "Procedure", "Guide", "Report", "Manual"]
    doc_type = random.choice(doc_types)

    document = Document(
        id=doc_id,
        source=DocumentSource.GOOGLE_DRIVE,
        sections=[],
        metadata={
            "company": company_name,
            "document_type": doc_type,
            "department": random.choice(
                ["HR", "Engineering", "Sales", "Marketing", "Finance"]
            ),
        },
        semantic_identifier=f"{company_name} {doc_type} Document",
    )

    chunk = IndexChunk(
        chunk_id=chunk_id,
        blurb=f"This is a {doc_type.lower()} document from {company_name}. Chunk {chunk_id}.",
        content=f"Content for chunk {chunk_id} of {doc_type} document {doc_id}. "
        f"This document contains important information for {company_name} employees. "
        f"This is realistic test content for testing purposes.",
        source_links={},
        section_continuation=False,
        source_document=document,
        title_prefix=f"{company_name} {doc_type}",
        metadata_suffix_semantic="",
        metadata_suffix_keyword="",
        doc_summary="",
        chunk_context="",
        mini_chunk_texts=None,
        contextual_rag_reserved_tokens=0,
        embeddings=ChunkEmbedding(
            full_embedding=generate_random_embedding(embedding_dim),
            mini_chunk_embeddings=[],
        ),
        title_embedding=generate_random_embedding(embedding_dim),
        large_chunk_id=None,
        large_chunk_reference_ids=[],
        image_file_id=None,
    )

    # Create document sets
    document_set_names = [
        f"{company_name} Document Set {i}" for i in range(number_of_document_sets)
    ]

    # Create ACL entries
    user_emails: list[str | None] = [
        f"user_{i}@{company_name.lower().replace(' ', '')}.com"
        for i in range(number_of_acl_entries)
    ]
    user_groups = [f"group_{i}" for i in range(number_of_acl_entries)]

    return DocMetadataAwareIndexChunk.from_index_chunk(
        index_chunk=chunk,
        user_project=[],
        access=DocumentAccess.build(
            user_emails=user_emails,
            user_groups=user_groups,
            external_user_emails=[],
            external_user_group_ids=[],
            is_public=random.choice([True, False]),
        ),
        document_sets={doc_set for doc_set in document_set_names},
        boost=random.randint(-1, 1),
        aggregated_chunk_boost_factor=random.random(),
        tenant_id=tenant_id,
    )


def seed_documents_for_tenant(
    tenant_id: str,
    company_name: str,
    num_docs: int = 100,
    chunks_per_doc: int = 5,
    batch_size: int = 50,
) -> None:
    """Seed documents with realistic content for a specific tenant."""
    logger.info(
        f"Seeding {num_docs} documents ({chunks_per_doc} chunks each) for tenant {tenant_id}"
    )

    with get_session_with_tenant(tenant_id=tenant_id) as db_session:
        search_settings = get_current_search_settings(db_session)
        multipass_config = get_multipass_config(search_settings)
        index_name = search_settings.index_name
        embedding_dim = search_settings.final_embedding_dim

    vespa_index = VespaIndex(
        index_name=index_name,
        secondary_index_name=None,
        large_chunks_enabled=multipass_config.enable_large_chunks,
        secondary_large_chunks_enabled=None,
    )

    all_chunks = []
    chunk_count = 0
    total_chunks = num_docs * chunks_per_doc

    for doc_num in range(num_docs):
        doc_id = f"doc_{tenant_id}_{doc_num}_{datetime.now().isoformat()}"
        for chunk_num in range(chunks_per_doc):
            chunk = generate_dummy_chunk(
                doc_id=doc_id,
                chunk_id=chunk_num,
                embedding_dim=embedding_dim,
                tenant_id=tenant_id,
                company_name=company_name,
            )
            all_chunks.append(chunk)
            chunk_count += 1

            if len(all_chunks) >= chunks_per_doc * batch_size:
                insertion_records = vespa_index.index(
                    chunks=all_chunks,
                    index_batch_params=IndexBatchParams(
                        doc_id_to_previous_chunk_cnt={},
                        doc_id_to_new_chunk_cnt={},
                        tenant_id=tenant_id,
                        large_chunks_enabled=False,
                    ),
                )
                logger.info(
                    f"Indexed {chunk_count}/{total_chunks} chunks ({chunk_count * 100 / total_chunks:.1f}%)"
                )
                all_chunks = []

    # Index remaining chunks
    if all_chunks:
        insertion_records = vespa_index.index(
            chunks=all_chunks,
            index_batch_params=IndexBatchParams(
                doc_id_to_previous_chunk_cnt={},
                doc_id_to_new_chunk_cnt={},
                tenant_id=tenant_id,
                large_chunks_enabled=False,
            ),
        )

    logger.info(f"✓ Finished seeding documents for tenant {tenant_id}")


def main() -> None:
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description="Seed multi-tenant dev database with realistic test data"
    )
    parser.add_argument(
        "--tenants",
        type=int,
        default=3,
        help="Number of tenants to create (default: 3)",
    )
    parser.add_argument(
        "--sessions-per-tenant",
        type=int,
        default=50,
        help="Number of chat sessions per tenant (default: 50)",
    )
    parser.add_argument(
        "--messages-per-session",
        type=int,
        default=4,
        help="Number of messages per chat session (default: 4)",
    )
    parser.add_argument(
        "--days-of-history",
        type=int,
        default=90,
        help="Number of days to spread chat history across (default: 90)",
    )
    parser.add_argument(
        "--docs-per-tenant",
        type=int,
        default=100,
        help="Number of documents per tenant (default: 100)",
    )
    parser.add_argument(
        "--chunks-per-doc",
        type=int,
        default=5,
        help="Number of chunks per document (default: 5)",
    )
    parser.add_argument(
        "--skip-chat",
        action="store_true",
        help="Skip seeding chat history",
    )
    parser.add_argument(
        "--skip-docs",
        action="store_true",
        help="Skip seeding documents",
    )
    parser.add_argument(
        "--api-url",
        type=str,
        default=API_SERVER_URL,
        help=f"API server URL (default: {API_SERVER_URL})",
    )

    args = parser.parse_args()

    # Initialize the SQL engine
    SqlEngine.init_engine(pool_size=10, max_overflow=5)

    # Use provided API URL or default
    api_url = args.api_url

    logger.info("=" * 80)
    logger.info("Multi-Tenant Dev Database Seeding Script")
    logger.info("=" * 80)
    logger.info(f"API Server: {api_url}")
    logger.info(f"Tenants to create: {args.tenants}")
    logger.info(f"Chat sessions per tenant: {args.sessions_per_tenant}")
    logger.info(f"Messages per session: {args.messages_per_session}")
    logger.info(f"Documents per tenant: {args.docs_per_tenant}")
    logger.info(f"Chunks per document: {args.chunks_per_doc}")
    logger.info("=" * 80)

    # Check if API server is accessible
    try:
        response = requests.get(f"{api_url}/health", timeout=5)
        response.raise_for_status()
        logger.info("✓ API server is accessible")
    except Exception as e:
        logger.error(f"✗ Cannot reach API server at {api_url}: {e}")
        logger.error("Make sure the multi-tenant dev environment is running:")
        logger.error(
            "  docker-compose -f deployment/docker_compose/docker-compose.multitenant-dev.yml up"
        )
        sys.exit(1)

    # Create tenants
    logger.info("")
    logger.info("Step 1: Creating tenants...")
    logger.info("-" * 80)

    tenants: list[TenantData] = []
    company_names = random.sample(
        SAMPLE_COMPANIES, min(args.tenants, len(SAMPLE_COMPANIES))
    )

    # If we need more tenants than sample companies, generate additional names
    if args.tenants > len(SAMPLE_COMPANIES):
        for i in range(args.tenants - len(SAMPLE_COMPANIES)):
            company_names.append(f"Company {i+1}")

    for company_name in company_names[: args.tenants]:
        tenant = create_tenant(company_name, api_url)
        if tenant:
            tenants.append(tenant)
        time.sleep(1)  # Small delay between tenant creation

    if not tenants:
        logger.error("✗ Failed to create any tenants!")
        sys.exit(1)

    logger.info(f"✓ Successfully created {len(tenants)} tenants")

    # Seed chat history
    if not args.skip_chat:
        logger.info("")
        logger.info("Step 2: Seeding chat history...")
        logger.info("-" * 80)

        for idx, tenant in enumerate(tenants, 1):
            logger.info(
                f"[{idx}/{len(tenants)}] Seeding chat history for {tenant.company_name}..."
            )
            try:
                seed_chat_history_for_tenant(
                    tenant.tenant_id,
                    args.sessions_per_tenant,
                    args.messages_per_session,
                    args.days_of_history,
                )
            except Exception as e:
                logger.error(
                    f"✗ Failed to seed chat history for tenant {tenant.tenant_id}: {e}"
                )

        logger.info("✓ Finished seeding chat history for all tenants")
    else:
        logger.info("Skipping chat history seeding (--skip-chat)")

    # Seed documents
    if not args.skip_docs:
        logger.info("")
        logger.info("Step 3: Seeding documents...")
        logger.info("-" * 80)

        for idx, tenant in enumerate(tenants, 1):
            logger.info(
                f"[{idx}/{len(tenants)}] Seeding documents for {tenant.company_name}..."
            )
            try:
                seed_documents_for_tenant(
                    tenant.tenant_id,
                    tenant.company_name,
                    args.docs_per_tenant,
                    args.chunks_per_doc,
                )
            except Exception as e:
                logger.error(
                    f"✗ Failed to seed documents for tenant {tenant.tenant_id}: {e}"
                )

        logger.info("✓ Finished seeding documents for all tenants")
    else:
        logger.info("Skipping document seeding (--skip-docs)")

    # Summary
    logger.info("")
    logger.info("=" * 80)
    logger.info("SEEDING COMPLETE!")
    logger.info("=" * 80)
    logger.info(f"Created {len(tenants)} tenants:")
    for tenant in tenants:
        logger.info(
            f"  - {tenant.company_name}: {tenant.admin_email} (password: {tenant.admin_password})"
        )
    logger.info("")
    logger.info(f"Total chat sessions: {len(tenants) * args.sessions_per_tenant}")
    logger.info(
        f"Total chat messages: {len(tenants) * args.sessions_per_tenant * args.messages_per_session}"
    )
    logger.info(f"Total documents: {len(tenants) * args.docs_per_tenant}")
    logger.info(
        f"Total chunks: {len(tenants) * args.docs_per_tenant * args.chunks_per_doc}"
    )
    logger.info("")
    logger.info("You can now test multi-tenant upgrades on this populated database!")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()
