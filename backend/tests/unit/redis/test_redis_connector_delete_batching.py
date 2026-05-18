import uuid
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from celery import Celery
from sqlalchemy.orm import Session

from onyx.redis.redis_connector_delete import RedisConnectorDelete


@pytest.fixture
def mock_redis():
    """Mock Redis client."""
    return MagicMock()


@pytest.fixture
def mock_pipeline():
    """Mock TenantRedisPipeline."""
    return MagicMock()


@pytest.fixture
def redis_connector_delete(mock_redis):
    """Create a RedisConnectorDelete instance with mocked Redis."""
    rc = RedisConnectorDelete(
        tenant_id="test_tenant",
        id=123,
        redis=mock_redis,
    )
    return rc


def test_generate_tasks_batches_250_documents(redis_connector_delete, mock_redis):  # noqa: ARG001
    """Test that 250 documents are split into 3 batches (100, 100, 50)."""
    # Mock the cc_pair
    mock_cc_pair = MagicMock()
    mock_cc_pair.connector_id = 1
    mock_cc_pair.credential_id = 1

    # Mock the document IDs (250 total)
    doc_ids = [str(uuid.uuid4()) for _ in range(250)]

    # Mock the celery app
    mock_celery_app = MagicMock(spec=Celery)

    # Mock the database session
    mock_db_session = MagicMock(spec=Session)

    # Create a generator that yields the doc_ids
    def mock_yield_per(n):  # noqa: ARG001
        for doc_id in doc_ids:
            yield doc_id

    mock_query_result = MagicMock()
    mock_query_result.yield_per = mock_yield_per

    mock_db_session.scalars = MagicMock(return_value=mock_query_result)

    # Mock the lock
    mock_lock = MagicMock()

    # Patch the get_connector_credential_pair_from_id
    with (
        patch(
            "onyx.redis.redis_connector_delete.get_connector_credential_pair_from_id",
            return_value=mock_cc_pair,
        ),
        patch(
            "onyx.redis.redis_connector_delete.TenantRedisPipeline"
        ) as mock_pipeline_class,
        patch(
            "onyx.redis.redis_connector_delete.construct_document_id_select_for_connector_credential_pair"
        ) as mock_construct_stmt,
    ):
        mock_pipeline_instance = MagicMock()
        mock_pipeline_class.return_value = mock_pipeline_instance

        mock_construct_stmt.return_value = MagicMock()

        # Call generate_tasks
        num_tasks_sent = redis_connector_delete.generate_tasks(
            celery_app=mock_celery_app,
            db_session=mock_db_session,
            lock=mock_lock,
        )

        # Assert that 3 tasks were sent (100 + 100 + 50)
        assert num_tasks_sent == 3

        # Assert that send_task was called 3 times
        assert mock_celery_app.send_task.call_count == 3

        # Verify the batches were correct sizes by looking at the kwargs
        calls = mock_celery_app.send_task.call_args_list
        batch_sizes = [len(call[1]["kwargs"]["document_ids"]) for call in calls]
        assert batch_sizes == [100, 100, 50]


def test_generate_tasks_single_batch_50_documents(redis_connector_delete, mock_redis):  # noqa: ARG001
    """Test that 50 documents result in a single batch."""
    mock_cc_pair = MagicMock()
    mock_cc_pair.connector_id = 1
    mock_cc_pair.credential_id = 1

    doc_ids = [str(uuid.uuid4()) for _ in range(50)]

    mock_celery_app = MagicMock(spec=Celery)
    mock_db_session = MagicMock(spec=Session)
    mock_lock = MagicMock()

    def mock_yield_per(n):  # noqa: ARG001
        for doc_id in doc_ids:
            yield doc_id

    mock_query_result = MagicMock()
    mock_query_result.yield_per = mock_yield_per

    mock_db_session.scalars = MagicMock(return_value=mock_query_result)

    with (
        patch(
            "onyx.redis.redis_connector_delete.get_connector_credential_pair_from_id",
            return_value=mock_cc_pair,
        ),
        patch("onyx.redis.redis_connector_delete.TenantRedisPipeline"),
        patch(
            "onyx.redis.redis_connector_delete.construct_document_id_select_for_connector_credential_pair"
        ) as mock_construct_stmt,
    ):
        mock_construct_stmt.return_value = MagicMock()

        num_tasks_sent = redis_connector_delete.generate_tasks(
            celery_app=mock_celery_app,
            db_session=mock_db_session,
            lock=mock_lock,
        )

        # Assert that 1 task was sent with 50 documents
        assert num_tasks_sent == 1

        assert mock_celery_app.send_task.call_count == 1
        call_kwargs = mock_celery_app.send_task.call_args[1]["kwargs"]
        assert len(call_kwargs["document_ids"]) == 50


def test_generate_tasks_full_batch_100_documents(redis_connector_delete, mock_redis):  # noqa: ARG001
    """Test that exactly 100 documents result in a single batch."""
    mock_cc_pair = MagicMock()
    mock_cc_pair.connector_id = 1
    mock_cc_pair.credential_id = 1

    doc_ids = [str(uuid.uuid4()) for _ in range(100)]

    mock_celery_app = MagicMock(spec=Celery)
    mock_db_session = MagicMock(spec=Session)
    mock_lock = MagicMock()

    def mock_yield_per(n):  # noqa: ARG001
        for doc_id in doc_ids:
            yield doc_id

    mock_query_result = MagicMock()
    mock_query_result.yield_per = mock_yield_per

    mock_db_session.scalars = MagicMock(return_value=mock_query_result)

    with (
        patch(
            "onyx.redis.redis_connector_delete.get_connector_credential_pair_from_id",
            return_value=mock_cc_pair,
        ),
        patch("onyx.redis.redis_connector_delete.TenantRedisPipeline"),
        patch(
            "onyx.redis.redis_connector_delete.construct_document_id_select_for_connector_credential_pair"
        ) as mock_construct_stmt,
    ):
        mock_construct_stmt.return_value = MagicMock()

        num_tasks_sent = redis_connector_delete.generate_tasks(
            celery_app=mock_celery_app,
            db_session=mock_db_session,
            lock=mock_lock,
        )

        # Assert that 1 task was sent with 100 documents
        assert num_tasks_sent == 1

        assert mock_celery_app.send_task.call_count == 1
        call_kwargs = mock_celery_app.send_task.call_args[1]["kwargs"]
        assert len(call_kwargs["document_ids"]) == 100


def test_generate_tasks_uses_pipeline_for_redis(redis_connector_delete, mock_redis):  # noqa: ARG001
    """Test that TenantRedisPipeline is used for batching Redis calls."""
    mock_cc_pair = MagicMock()
    mock_cc_pair.connector_id = 1
    mock_cc_pair.credential_id = 1

    doc_ids = [str(uuid.uuid4()) for _ in range(150)]

    mock_celery_app = MagicMock(spec=Celery)
    mock_db_session = MagicMock(spec=Session)
    mock_lock = MagicMock()

    def mock_yield_per(n):  # noqa: ARG001
        for doc_id in doc_ids:
            yield doc_id

    mock_query_result = MagicMock()
    mock_query_result.yield_per = mock_yield_per

    mock_db_session.scalars = MagicMock(return_value=mock_query_result)

    with (
        patch(
            "onyx.redis.redis_connector_delete.get_connector_credential_pair_from_id",
            return_value=mock_cc_pair,
        ),
        patch(
            "onyx.redis.redis_connector_delete.TenantRedisPipeline"
        ) as mock_pipeline_class,
        patch(
            "onyx.redis.redis_connector_delete.construct_document_id_select_for_connector_credential_pair"
        ) as mock_construct_stmt,
    ):
        mock_pipeline_instance = MagicMock()
        mock_pipeline_class.return_value = mock_pipeline_instance

        mock_construct_stmt.return_value = MagicMock()

        num_tasks_sent = redis_connector_delete.generate_tasks(
            celery_app=mock_celery_app,
            db_session=mock_db_session,
            lock=mock_lock,
        )

        # Assert that 2 tasks were sent (150 = 100 + 50)
        assert num_tasks_sent == 2

        # Assert that pipeline was created twice (once per batch)
        assert mock_redis.pipeline.call_count == 2

        # Assert that sadd and expire were called on the pipeline
        for call in mock_pipeline_instance.method_calls:
            # Each batch should call sadd and expire
            assert any(
                "sadd" in str(call) for call in mock_pipeline_instance.method_calls
            )
            assert any(
                "expire" in str(call) for call in mock_pipeline_instance.method_calls
            )

        # Assert that execute was called twice (once per batch)
        assert mock_pipeline_instance.execute.call_count == 2
