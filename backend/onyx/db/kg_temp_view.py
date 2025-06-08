from sqlalchemy import text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session

from onyx.configs.app_configs import DB_READONLY_USER


Base = declarative_base()


def get_user_view_names(user_email: str) -> tuple[str, str]:
    user_email_cleaned = user_email.replace("@", "_").replace(".", "_")
    return (
        f"allowed_docs_{user_email_cleaned}",
        f"kg_relationships_with_access_{user_email_cleaned}",
    )


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
    WITH kg_used_docs AS (
        SELECT document_id as kg_used_doc_id
        FROM kg_entity d
        WHERE document_id IS NOT NULL
    ),

    public_docs AS (
        SELECT d.id as allowed_doc_id
        FROM document d
        INNER JOIN kg_used_docs kud ON kud.kg_used_doc_id = d.id
        WHERE d.is_public
    ),
    user_owned_docs AS (
        SELECT d.id as allowed_doc_id
        FROM document_by_connector_credential_pair d
        JOIN credential c ON d.credential_id = c.id
        JOIN connector_credential_pair ccp ON
            d.connector_id = ccp.connector_id AND
            d.credential_id = ccp.credential_id
        JOIN "user" u ON c.user_id = u.id
        INNER JOIN kg_used_docs kud ON kud.kg_used_doc_id = d.id
        WHERE ccp.status != 'DELETING'
        AND ccp.access_type != 'SYNC'
        AND u.email = :user_email
    ),
    user_group_accessible_docs AS (
        SELECT d.id as allowed_doc_id
        FROM document_by_connector_credential_pair d
        JOIN connector_credential_pair ccp ON
            d.connector_id = ccp.connector_id AND
            d.credential_id = ccp.credential_id
        JOIN user_group__connector_credential_pair ugccp ON
            ccp.id = ugccp.cc_pair_id
        JOIN user__user_group uug ON
            uug.user_group_id = ugccp.user_group_id
        JOIN "user" u ON uug.user_id = u.id
        INNER JOIN kg_used_docs kud ON kud.kg_used_doc_id = d.id
        WHERE kud.kg_used_doc_id IS NOT NULL
        AND ccp.status != 'DELETING'
        AND ccp.access_type != 'SYNC'
        AND u.email = :user_email
    ),
    external_user_docs AS (
        SELECT d.id as allowed_doc_id
        FROM document d
        INNER JOIN kg_used_docs kud ON kud.kg_used_doc_id = d.id
        WHERE kud.kg_used_doc_id IS NOT NULL
        AND :user_email = ANY(external_user_emails)
    ),
    external_group_docs AS (
        SELECT d.id as allowed_doc_id
        FROM document d
        INNER JOIN kg_used_docs kud ON kud.kg_used_doc_id = d.id
        JOIN user__external_user_group_id ueg ON ueg.external_user_group_id = ANY(d.external_user_group_ids)
        JOIN "user" u ON ueg.user_id = u.id
        WHERE kud.kg_used_doc_id IS NOT NULL
        AND u.email = :user_email
    )
    SELECT DISTINCT allowed_doc_id FROM (
        SELECT allowed_doc_id FROM public_docs
        UNION
        SELECT allowed_doc_id FROM user_owned_docs
        UNION
        SELECT allowed_doc_id FROM user_group_accessible_docs
        UNION
        SELECT allowed_doc_id FROM external_user_docs
        UNION
        SELECT allowed_doc_id FROM external_group_docs
    ) combined_docs
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
           d.doc_updated_at as source_date,
           se.attributes as source_entity_attributes,
           te.attributes as target_entity_attributes
    FROM kg_relationship kgr
    INNER JOIN {allowed_docs_view_name} AD on AD.allowed_doc_id = kgr.source_document
    JOIN document d on d.id = kgr.source_document
    JOIN kg_entity se on se.id_name = kgr.source_node
    JOIN kg_entity te on te.id_name = kgr.target_node
    """
    )

    # Execute the views using the session
    db_session.execute(allowed_docs_view)
    db_session.execute(kg_relationships_view)

    # Grant permissions on view to readonly user

    db_session.execute(
        text(f"GRANT SELECT ON {kg_relationships_view_name} TO {DB_READONLY_USER}")
    )

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
    # First revoke access from the readonly user
    revoke_kg_relationships = text(
        f"REVOKE SELECT ON {kg_relationships_view_name} FROM {DB_READONLY_USER}"
    )

    db_session.execute(revoke_kg_relationships)

    # Drop the views in reverse order of creation to handle dependencies
    drop_kg_relationships = text(f"DROP VIEW IF EXISTS {kg_relationships_view_name}")
    drop_allowed_docs = text(f"DROP VIEW IF EXISTS {allowed_docs_view_name}")

    db_session.execute(drop_kg_relationships)
    db_session.execute(drop_allowed_docs)
    db_session.commit()
    return None
