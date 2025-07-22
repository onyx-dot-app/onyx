import random

from sqlalchemy import text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session

from onyx.agents.agent_search.kb_search.models import KGViewNames
from onyx.configs.app_configs import DB_READONLY_USER
from onyx.configs.kg_configs import KG_TEMP_ALLOWED_DOCS_VIEW_NAME_PREFIX
from onyx.configs.kg_configs import KG_TEMP_KG_ENTITIES_VIEW_NAME_PREFIX
from onyx.configs.kg_configs import KG_TEMP_KG_RELATIONSHIPS_VIEW_NAME_PREFIX
from onyx.db.engine.sql_engine import get_session_with_current_tenant


Base = declarative_base()


def get_user_view_names(user_email: str, tenant_id: str) -> KGViewNames:
    user_email_cleaned = (
        user_email.replace("@", "__").replace(".", "_").replace("+", "_")
    )
    random_suffix_str = str(random.randint(1000000, 9999999))
    return KGViewNames(
        allowed_docs_view_name=f'"{tenant_id}".{KG_TEMP_ALLOWED_DOCS_VIEW_NAME_PREFIX}_{user_email_cleaned}_{random_suffix_str}',
        kg_relationships_view_name=f'"{tenant_id}".{KG_TEMP_KG_RELATIONSHIPS_VIEW_NAME_PREFIX}_{user_email_cleaned}_{random_suffix_str}',
        kg_entity_view_name=f'"{tenant_id}".{KG_TEMP_KG_ENTITIES_VIEW_NAME_PREFIX}_{user_email_cleaned}_{random_suffix_str}',
    )


# First, create the view definition
def create_views(
    db_session: Session,
    tenant_id: str,
    user_email: str,
    allowed_docs_view_name: str,
    kg_relationships_view_name: str,
    kg_entity_view_name: str,
) -> None:

    # Create ALLOWED_DOCS view
    allowed_docs_view = text(
        f"""
    CREATE OR REPLACE VIEW {allowed_docs_view_name} AS
    WITH kg_used_docs AS (
        SELECT document_id as kg_used_doc_id
        FROM "{tenant_id}".kg_entity d
        WHERE document_id IS NOT NULL
    ),

    base_public_docs AS (
        SELECT d.id as allowed_doc_id
        FROM "{tenant_id}".document d
        INNER JOIN kg_used_docs kud ON kud.kg_used_doc_id = d.id
        WHERE d.is_public
    ),
    user_owned_and_public_docs AS (
        SELECT d.id as allowed_doc_id
        FROM "{tenant_id}".document_by_connector_credential_pair d
        JOIN "{tenant_id}".credential c ON d.credential_id = c.id
        JOIN "{tenant_id}".connector_credential_pair ccp ON
            d.connector_id = ccp.connector_id AND
            d.credential_id = ccp.credential_id
        JOIN "{tenant_id}".user u ON c.user_id = u.id
        INNER JOIN kg_used_docs kud ON kud.kg_used_doc_id = d.id
        WHERE ccp.status != 'DELETING'
        AND ccp.access_type != 'SYNC'
        AND (u.email = :user_email or ccp.access_type::text = 'PUBLIC')
    ),
    user_group_accessible_docs AS (
        SELECT d.id as allowed_doc_id
        FROM "{tenant_id}".document_by_connector_credential_pair d
        JOIN "{tenant_id}".connector_credential_pair ccp ON
            d.connector_id = ccp.connector_id AND
            d.credential_id = ccp.credential_id
        JOIN "{tenant_id}".user_group__connector_credential_pair ugccp ON
            ccp.id = ugccp.cc_pair_id
        JOIN "{tenant_id}".user__user_group uug ON
            uug.user_group_id = ugccp.user_group_id
        JOIN "{tenant_id}".user u ON uug.user_id = u.id
        INNER JOIN kg_used_docs kud ON kud.kg_used_doc_id = d.id
        WHERE kud.kg_used_doc_id IS NOT NULL
        AND ccp.status != 'DELETING'
        AND ccp.access_type != 'SYNC'
        AND u.email = :user_email
    ),
    external_user_docs AS (
        SELECT d.id as allowed_doc_id
        FROM "{tenant_id}".document d
        INNER JOIN kg_used_docs kud ON kud.kg_used_doc_id = d.id
        WHERE kud.kg_used_doc_id IS NOT NULL
        AND :user_email = ANY(external_user_emails)
    ),
    external_group_docs AS (
        SELECT d.id as allowed_doc_id
        FROM "{tenant_id}".document d
        INNER JOIN kg_used_docs kud ON kud.kg_used_doc_id = d.id
        JOIN "{tenant_id}".user__external_user_group_id ueg ON ueg.external_user_group_id = ANY(d.external_user_group_ids)
        JOIN "{tenant_id}".user u ON ueg.user_id = u.id
        WHERE kud.kg_used_doc_id IS NOT NULL
        AND u.email = :user_email
    )
    SELECT DISTINCT allowed_doc_id FROM (
        SELECT allowed_doc_id FROM base_public_docs
        UNION
        SELECT allowed_doc_id FROM user_owned_and_public_docs
        UNION
        SELECT allowed_doc_id FROM user_group_accessible_docs
        UNION
        SELECT allowed_doc_id FROM external_user_docs
        UNION
        SELECT allowed_doc_id FROM external_group_docs
    ) combined_docs
    """
    ).bindparams(user_email=user_email)

    # Create the main view that uses ALLOWED_DOCS for Relationships
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
    FROM "{tenant_id}".kg_relationship kgr
    INNER JOIN {allowed_docs_view_name} AD on AD.allowed_doc_id = kgr.source_document
    JOIN "{tenant_id}".document d on d.id = kgr.source_document
    JOIN "{tenant_id}".kg_entity se on se.id_name = kgr.source_node
    JOIN "{tenant_id}".kg_entity te on te.id_name = kgr.target_node
    """
    )

    # Create the main view that uses ALLOWED_DOCS for Entities
    kg_entity_view = text(
        f"""
    CREATE OR REPLACE VIEW {kg_entity_view_name} AS
    SELECT kge.id_name as entity,
           kge.entity_type_id_name as entity_type,
           kge.attributes as entity_attributes,
           kge.document_id as source_document,
           d.doc_updated_at as source_date
    FROM "{tenant_id}".kg_entity kge
    INNER JOIN {allowed_docs_view_name} AD on AD.allowed_doc_id = kge.document_id
    JOIN "{tenant_id}".document d on d.id = kge.document_id
    """
    )

    # Execute the views using the session
    db_session.execute(allowed_docs_view)
    db_session.execute(kg_relationships_view)
    db_session.execute(kg_entity_view)

    # Grant permissions on view to readonly user

    db_session.execute(
        text(f"GRANT SELECT ON {kg_relationships_view_name} TO {DB_READONLY_USER}")
    )
    db_session.execute(
        text(f"GRANT SELECT ON {kg_entity_view_name} TO {DB_READONLY_USER}")
    )

    db_session.commit()

    return None


def drop_views(
    allowed_docs_view_name: str | None = None,
    kg_relationships_view_name: str | None = None,
    kg_entity_view_name: str | None = None,
) -> None:
    """
    Drops the temporary views created by create_views.

    Args:
        db_session: SQLAlchemy session
        allowed_docs_view_name: Name of the allowed_docs view
        kg_relationships_view_name: Name of the allowed kg_relationships view
        kg_entity_view_name: Name of the allowed kg_entity view
    """

    with get_session_with_current_tenant() as db_drop_session:
        if kg_relationships_view_name:
            revoke_kg_relationships = text(
                f"REVOKE SELECT ON {kg_relationships_view_name} FROM {DB_READONLY_USER}"
            )
            db_drop_session.execute(revoke_kg_relationships)
            drop_kg_relationships = text(
                f"DROP VIEW IF EXISTS {kg_relationships_view_name}"
            )
            db_drop_session.execute(drop_kg_relationships)

        if kg_entity_view_name:
            revoke_kg_entities = text(
                f"REVOKE SELECT ON {kg_entity_view_name} FROM {DB_READONLY_USER}"
            )
            db_drop_session.execute(revoke_kg_entities)
            drop_kg_entities = text(f"DROP VIEW IF EXISTS {kg_entity_view_name}")
            db_drop_session.execute(drop_kg_entities)

        if allowed_docs_view_name:
            drop_allowed_docs = text(f"DROP VIEW IF EXISTS {allowed_docs_view_name}")
            db_drop_session.execute(drop_allowed_docs)

        db_drop_session.commit()
    return None
