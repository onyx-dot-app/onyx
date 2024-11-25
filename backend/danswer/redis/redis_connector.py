import redis

from danswer.redis.redis_connector_delete import RedisConnectorDelete
from danswer.redis.redis_connector_index import RedisConnectorIndex
from danswer.redis.redis_connector_prune import RedisConnectorPrune
from danswer.redis.redis_connector_stop import RedisConnectorStop
from danswer.redis.redis_pool import get_redis_client


class RedisConnector:
    """Composes several classes to simplify interacting with a connector and its
    associated background tasks / associated redis interactions."""

    def __init__(self, tenant_id: str | None, id: int) -> None:
        self.tenant_id: str | None = tenant_id
        self.id: int = id
        self.redis: redis.Redis = get_redis_client(tenant_id=tenant_id)

        self.stop = RedisConnectorStop(tenant_id, id, self.redis)
        self.prune = RedisConnectorPrune(tenant_id, id, self.redis)
        self.delete = RedisConnectorDelete(tenant_id, id, self.redis)

    def new_index(self, search_settings_id: int) -> RedisConnectorIndex:
        return RedisConnectorIndex(
            self.tenant_id, self.id, search_settings_id, self.redis
        )

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
