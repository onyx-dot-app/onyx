import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

from onyx.configs.app_configs import DB_USER_DATABASE
from onyx.configs.app_configs import DB_USER_PASSWORD
from onyx.configs.app_configs import DB_USER_USERNAME
from onyx.db.engine import SqlEngine

logger = logging.getLogger(__name__)


async def create_database_user(db_session: Session) -> None:
    """
    Create a read-only database user with no privileges initially.
    This should be called during application startup.
    """
    try:
        # Create user if it doesn't exist
        create_user_sql = text(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '{DB_USER_USERNAME}') THEN
                    CREATE USER {DB_USER_USERNAME} WITH PASSWORD '{DB_USER_PASSWORD}';
                    GRANT CONNECT ON DATABASE {DB_USER_DATABASE} TO {DB_USER_USERNAME};
                END IF;
            END
            $$;
        """
        )

        # Execute the SQL
        db_session.execute(create_user_sql)
        db_session.commit()

        logger.info(
            f"Read-only database user {DB_USER_USERNAME} created successfully with minimal privileges"
        )

    except Exception as e:
        logger.error(f"Failed to create database user: {str(e)}")
        raise


async def initialize_application() -> None:
    """
    Initialize application components at startup.
    This function is called during the FastAPI lifespan event.
    """
    try:
        # Get the database engine
        engine = SqlEngine.get_engine()

        # Create a session
        with Session(engine) as db_session:
            # Create the database user
            await create_database_user(db_session)

        logger.info("Application initialization complete")

    except Exception as e:
        logger.error(f"Failed to initialize application: {str(e)}")
        raise
