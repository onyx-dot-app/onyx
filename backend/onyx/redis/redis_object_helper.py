from abc import ABC
from abc import abstractmethod

from celery import Celery
from redis import Redis
from redis.lock import Lock as RedisLock
from sqlalchemy.orm import Session

from onyx.redis.redis_pool import get_redis_client


class RedisObjectHelper(ABC):
    PREFIX = "base"
    FENCE_PREFIX = PREFIX + "_fence"
    TASKSET_PREFIX = PREFIX + "_taskset"

    def __init__(self, tenant_id: str, id: str):
        self._tenant_id: str = tenant_id
        self._id: str = id
        self.redis = get_redis_client(tenant_id=tenant_id)

    @property
    def task_id_prefix(self) -> str:
        return f"{self.PREFIX}_{self._id}"

    @property
    def fence_key(self) -> str:
        # example: documentset_fence_1
        return f"{self.FENCE_PREFIX}_{self._id}"

    @property
    def taskset_key(self) -> str:
        # example: documentset_taskset_1
        return f"{self.TASKSET_PREFIX}_{self._id}"

    @staticmethod
    def get_id_from_fence_key(key: str) -> str | None:
        """
        Extracts the object ID from a fence key in the format `PREFIX_fence_X`.

        Args:
            key (str): The fence key string.

        Returns:
            Optional[int]: The extracted ID if the key is in the correct format, otherwise None.
        """
        parts = key.split("_")
        if len(parts) != 3:
            return None

        object_id = parts[2]
        return object_id

    @staticmethod
    def get_id_from_task_id(task_id: str) -> str | None:
        """
        Extracts the object ID from a task ID string.

        This method assumes the task ID is formatted as `prefix_objectid_suffix`, where:
        - `prefix` is an arbitrary string (e.g., the name of the task or entity),
        - `objectid` is the ID you want to extract,
        - `suffix` is another arbitrary string (e.g., a UUID).

        Example:
            If the input `task_id` is `documentset_1_cbfdc96a-80ca-4312-a242-0bb68da3c1dc`,
            this method will return the string `"1"`.

        Args:
            task_id (str): The task ID string from which to extract the object ID.

        Returns:
            str | None: The extracted object ID if the task ID is in the correct format, otherwise None.
        """
        # example: task_id=documentset_1_cbfdc96a-80ca-4312-a242-0bb68da3c1dc
        parts = task_id.split("_")
        if len(parts) != 3:
            return None

        object_id = parts[1]
        return object_id

    @abstractmethod
    def generate_tasks(
        self,
        max_tasks: int,
        celery_app: Celery,
        db_session: Session,
        redis_client: Redis,
        lock: RedisLock,
        tenant_id: str,
    ) -> tuple[int, int] | None:
        """First element should be the number of actual tasks generated, second should
        be the number of docs that were candidates to be synced for the cc pair.

        The need for this is when we are syncing stale docs referenced by multiple
        connectors. In a single pass across multiple cc pairs, we only want a task
        for be created for a particular document id the first time we see it.
        The rest can be skipped."""
