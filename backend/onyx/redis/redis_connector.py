import time

import redis

from onyx.db.models import SearchSettings
from onyx.redis.redis_connector_delete import RedisConnectorDelete
from onyx.redis.redis_connector_doc_perm_sync import RedisConnectorPermissionSync
from onyx.redis.redis_connector_ext_group_sync import RedisConnectorExternalGroupSync
from onyx.redis.redis_connector_index import RedisConnectorIndex
from onyx.redis.redis_connector_prune import RedisConnectorPrune
from onyx.redis.redis_connector_stop import RedisConnectorStop
from onyx.redis.redis_pool import get_redis_client


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
        self.permissions = RedisConnectorPermissionSync(tenant_id, id, self.redis)
        self.external_group_sync = RedisConnectorExternalGroupSync(
            tenant_id, id, self.redis
        )

    def new_index(self, search_settings_id: int) -> RedisConnectorIndex:
        return RedisConnectorIndex(
            self.tenant_id, self.id, search_settings_id, self.redis
        )

    def wait_for_indexing_termination(
        self,
        search_settings_list: list[SearchSettings],
        timeout: float = 15.0,
    ) -> bool:
        """
        Returns True if all indexing for the given redis connector is finished within the given timeout.
        Returns False if the timeout is exceeded

        This check does not guarantee that current indexings being terminated
        won't get restarted midflight
        """

        finished = False

        start = time.monotonic()

        while True:
            still_indexing = False
            for search_settings in search_settings_list:
                redis_connector_index = self.new_index(search_settings.id)
                if redis_connector_index.fenced:
                    still_indexing = True
                    break

            if not still_indexing:
                finished = True
                break

            now = time.monotonic()
            if now - start > timeout:
                break

            time.sleep(1)
            continue

        return finished

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
