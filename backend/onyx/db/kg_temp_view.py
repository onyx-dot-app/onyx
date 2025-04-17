import os

from sqlalchemy import text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session

KG_READONLY_DB_USER = os.getenv("KG_READONLY_DB_USER")


Base = declarative_base()


# First, create the view definition
def create_views(
    db_session: Session,
    user_email: str,
    allowed_docs_view_name: str = "allowed_docs",
    kg_relationships_view_name: str = "kg_relationships_with_access",
) -> None:
    # Create ALLOWED_DOCS view
    allowed_docs_view = text(
        f"""
    CREATE OR REPLACE VIEW {allowed_docs_view_name} AS
    SELECT DISTINCT d.id as allowed_doc_id
    FROM document_by_connector_credential_pair d
    JOIN credential c ON d.credential_id = c.id
    JOIN connector_credential_pair ccp ON
        d.connector_id = ccp.connector_id AND
        d.credential_id = ccp.credential_id
    LEFT JOIN "user" u ON
        c.user_id = u.id AND
        ccp.access_type != 'SYNC'
    WHERE
        ccp.status != 'DELETING' AND
        (
            ccp.access_type = 'PUBLIC' OR
            u.email = :user_email
        )
    """
    ).bindparams(user_email=user_email)

    # Create the main view that uses ALLOWED_DOCS
    kg_relationships_view = text(
        f"""
    CREATE OR REPLACE VIEW {kg_relationships_view_name} AS
    SELECT kgr.id_name as relationship,
           kgr.source_node as source_entity,
           kgr.target_node as target_entity,
           kgr.source_node_type as source_entity_type,
           kgr.target_node_type as target_entity_type,
           kgr.type as relationship_description,
           kgr.relationship_type_id_name as relationship_type,
           kgr.source_document as source_document,
           d.doc_updated_at as source_date
    FROM kg_relationship kgr
    JOIN {allowed_docs_view_name} AD on AD.allowed_doc_id = kgr.source_document
    JOIN document d on d.id = kgr.source_document
    """
    )

    # Execute the views using the session
    db_session.execute(allowed_docs_view)
    db_session.execute(kg_relationships_view)

    grant_allowed_docs = text(
        f"GRANT SELECT ON {allowed_docs_view_name} TO {KG_READONLY_DB_USER}"
    )
    grant_kg_relationships = text(
        f"GRANT SELECT ON {kg_relationships_view_name} TO {KG_READONLY_DB_USER}"
    )
    db_session.execute(grant_allowed_docs)
    db_session.execute(grant_kg_relationships)

    db_session.commit()

    return None


def drop_views(
    db_session: Session,
    allowed_docs_view_name: str = "allowed_docs",
    kg_relationships_view_name: str = "kg_relationships_with_access",
) -> None:
    """
    Drops the temporary views created by create_views.

    Args:
        db_session: SQLAlchemy session
        allowed_docs_view_name: Name of the allowed_docs view
        kg_relationships_view_name: Name of the kg_relationships view
    """
    # Drop the views in reverse order of creation to handle dependencies
    drop_kg_relationships = text(f"DROP VIEW IF EXISTS {kg_relationships_view_name}")
    drop_allowed_docs = text(f"DROP VIEW IF EXISTS {allowed_docs_view_name}")

    db_session.execute(drop_kg_relationships)
    db_session.execute(drop_allowed_docs)
    db_session.commit()
    return None
