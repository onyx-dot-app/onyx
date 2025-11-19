import argparse
import json
import logging
import sys
import time
from enum import Enum
from logging import getLogger
from typing import cast
from uuid import UUID

from redis import Redis

from ee.onyx.server.tenants.user_mapping import get_tenant_id_for_email
from onyx.auth.invited_users import get_invited_users
from onyx.auth.invited_users import write_invited_users
from onyx.configs.app_configs import REDIS_AUTH_KEY_PREFIX
from onyx.configs.app_configs import REDIS_DB_NUMBER
from onyx.configs.app_configs import REDIS_HOST
from onyx.configs.app_configs import REDIS_PASSWORD
from onyx.configs.app_configs import REDIS_PORT
from onyx.configs.app_configs import REDIS_SSL
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.users import get_user_by_email
from onyx.redis.redis_connector import RedisConnector
from onyx.redis.redis_pool import RedisPool
from shared_configs.configs import MULTI_TENANT
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from shared_configs.contextvars import get_current_tenant_id

# Tool to run helpful operations on Redis in production
# This is targeted for internal usage and may not have all the necessary parameters
# for general usage across custom deployments

# Configure the logger
logging.basicConfig(
    level=logging.INFO,  # Set the log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",  # Log format
    handlers=[logging.StreamHandler()],  # Output logs to console
)

logger = getLogger(__name__)

SCAN_ITER_COUNT = 10000
BATCH_DEFAULT = 1000


class OnyxRedisCommand(Enum):
    purge_connectorsync_taskset = "purge_connectorsync_taskset"
    purge_documentset_taskset = "purge_documentset_taskset"
    purge_usergroup_taskset = "purge_usergroup_taskset"
    purge_locks_blocking_deletion = "purge_locks_blocking_deletion"
    purge_vespa_syncing = "purge_vespa_syncing"
    purge_pidbox = "purge_pidbox"
    get_user_token = "get_user_token"
    delete_user_token = "delete_user_token"
    add_invited_user = "add_invited_user"
    get_list_element = "get_list_element"

    def __str__(self) -> str:
        return self.value


def get_user_id(user_email: str) -> tuple[UUID, str]:
    tenant_id = (
        get_tenant_id_for_email(user_email) if MULTI_TENANT else POSTGRES_DEFAULT_SCHEMA
    )

    with get_session_with_tenant(tenant_id=tenant_id) as session:
        user = get_user_by_email(user_email, session)
        if user is None:
            raise ValueError(f"User not found for email: {user_email}")
        return user.id, tenant_id


def onyx_redis(
    command: OnyxRedisCommand,
    batch: int,
    dry_run: bool,
    ssl: bool,
    host: str,
    port: int,
    db: int,
    password: str | None,
    user_email: str | None = None,
    cc_pair_id: int | None = None,
) -> int:
    # this is global and not tenant aware
    pool = RedisPool.create_pool(
        host=host,
        port=port,
        db=db,
        password=password if password else "",
        ssl=ssl,
        ssl_cert_reqs="optional",
        ssl_ca_certs=None,
    )

    r = Redis(connection_pool=pool)

    logger.info("Redis ping starting. This may hang if your settings are incorrect.")

    try:
        r.ping()
    except:
        logger.exception("Redis ping exceptioned")
        raise

    logger.info("Redis ping succeeded.")

    if command == OnyxRedisCommand.purge_connectorsync_taskset:
        """Purge connector tasksets. Used when the tasks represented in the tasksets
        have been purged."""
        return purge_by_match_and_type(
            "*connectorsync_taskset*", "set", batch, dry_run, r
        )
    elif command == OnyxRedisCommand.purge_documentset_taskset:
        return purge_by_match_and_type(
            "*documentset_taskset*", "set", batch, dry_run, r
        )
    elif command == OnyxRedisCommand.purge_usergroup_taskset:
        return purge_by_match_and_type("*usergroup_taskset*", "set", batch, dry_run, r)
    elif command == OnyxRedisCommand.purge_locks_blocking_deletion:
        if cc_pair_id is None:
            logger.error("You must specify --cc-pair with purge_deletion_locks")
            return 1

        tenant_id = get_current_tenant_id()
        logger.info(f"Purging locks associated with deleting cc_pair={cc_pair_id}.")
        redis_connector = RedisConnector(tenant_id, cc_pair_id)

        redis_delete_if_exists_helper(
            f"{tenant_id}:{redis_connector.prune.fence_key}", dry_run, r
        )
        redis_delete_if_exists_helper(
            f"{tenant_id}:{redis_connector.permissions.fence_key}", dry_run, r
        )
        redis_delete_if_exists_helper(
            f"{tenant_id}:{redis_connector.external_group_sync.fence_key}", dry_run, r
        )
        return 0
    elif command == OnyxRedisCommand.purge_vespa_syncing:
        return purge_by_match_and_type(
            "*connectorsync:vespa_syncing*", "string", batch, dry_run, r
        )
    elif command == OnyxRedisCommand.purge_pidbox:
        return purge_by_match_and_type(
            "*reply.celery.pidbox", "list", batch, dry_run, r
        )
    elif command == OnyxRedisCommand.get_list_element:
        # just hardcoded for now
        result = r.lrange(
            "0097a564-d343-3c1f-9fd1-af8cce038115.reply.celery.pidbox", 0, 0
        )
        print(f"{result}")
        return 0
    elif command == OnyxRedisCommand.get_user_token:
        if not user_email:
            logger.error("You must specify --user-email with get_user_token")
            return 1
        token_key = get_user_token_from_redis(r, user_email)
        if token_key:
            print(f"Token key for user {user_email}: {token_key}")
            return 0
        else:
            print(f"No token found for user {user_email}")
            return 2
    elif command == OnyxRedisCommand.delete_user_token:
        if not user_email:
            logger.error("You must specify --user-email with delete_user_token")
            return 1
        if delete_user_token_from_redis(r, user_email, dry_run):
            return 0
        else:
            return 2
    elif command == OnyxRedisCommand.add_invited_user:
        if not user_email:
            logger.error("You must specify --user-email with add_invited_user")
            return 1
        current_invited_users = get_invited_users()
        if user_email not in current_invited_users:
            current_invited_users.append(user_email)
            if dry_run:
                logger.info(f"(DRY-RUN) Would add {user_email} to invited users")
            else:
                write_invited_users(current_invited_users)
                logger.info(f"Added {user_email} to invited users")
        else:
            logger.info(f"{user_email} is already in the invited users list")
        return 0
    else:
        pass

    return 255


def flush_batch_delete(batch_keys: list[bytes], r: Redis) -> None:
    logger.info(f"Flushing {len(batch_keys)} operations to Redis.")
    with r.pipeline() as pipe:
        for batch_key in batch_keys:
            pipe.delete(batch_key)
        pipe.execute()


def redis_delete_if_exists_helper(key: str, dry_run: bool, r: Redis) -> bool:
    """Returns True if the key was found, False if not.
    This function exists for logging purposes as the delete operation itself
    doesn't really need to check the existence of the key.
    """

    if not r.exists(key):
        logger.info(f"Did not find {key}.")
        return False

    if dry_run:
        logger.info(f"(DRY-RUN) Deleting {key}.")
    else:
        logger.info(f"Deleting {key}.")
        r.delete(key)

    return True


def purge_by_match_and_type(
    match_pattern: str, match_type: str, batch_size: int, dry_run: bool, r: Redis
) -> int:
    """match_pattern: glob style expression
    match_type: https://redis.io/docs/latest/commands/type/
    """

    logger.info(
        f"purge_by_match_and_type start: "
        f"match_pattern={match_pattern} "
        f"match_type={match_type}"
    )

    # cursor = "0"
    # while cursor != 0:
    #     cursor, data = self.scan(
    #         cursor=cursor, match=match, count=count, _type=_type, **kwargs
    #     )

    start = time.monotonic()

    count = 0
    batch_keys: list[bytes] = []
    for key in r.scan_iter(match_pattern, count=SCAN_ITER_COUNT, _type=match_type):
        # key_type = r.type(key)
        # if key_type != match_type.encode("utf-8"):
        #     continue

        key = cast(bytes, key)
        key_str = key.decode("utf-8")

        count += 1
        if dry_run:
            logger.info(f"(DRY-RUN) Deleting item {count}: {key_str}")
            continue

        logger.info(f"Deleting item {count}: {key_str}")

        batch_keys.append(key)

        # flush if batch size has been reached
        if len(batch_keys) >= batch_size:
            flush_batch_delete(batch_keys, r)
            batch_keys.clear()

    # final flush
    flush_batch_delete(batch_keys, r)
    batch_keys.clear()

    logger.info(f"Deleted {count} matches.")

    elapsed = time.monotonic() - start
    logger.info(f"Time elapsed: {elapsed:.2f}s")
    return 0


def get_user_token_from_redis(r: Redis, user_email: str) -> str | None:
    """
    Scans Redis keys for a user token that matches user_email or user_id fields.
    Returns the token key if found, else None.
    """
    user_id, tenant_id = get_user_id(user_email)

    # Scan for keys matching the auth key prefix
    auth_keys = r.scan_iter(f"{REDIS_AUTH_KEY_PREFIX}*", count=SCAN_ITER_COUNT)

    matching_key = None

    for key in auth_keys:
        key_str = key.decode("utf-8")
        jwt_token = r.get(key_str)

        if not jwt_token:
            continue

        try:
            jwt_token_str = (
                jwt_token.decode("utf-8")
                if isinstance(jwt_token, bytes)
                else str(jwt_token)
            )

            if jwt_token_str.startswith("b'") and jwt_token_str.endswith("'"):
                jwt_token_str = jwt_token_str[2:-1]  # Remove b'' wrapper

            jwt_data = json.loads(jwt_token_str)
            if jwt_data.get("tenant_id") == tenant_id and str(
                jwt_data.get("sub")
            ) == str(user_id):
                matching_key = key_str
                break
        except json.JSONDecodeError:
            logger.error(f"Failed to decode JSON for key: {key_str}")
        except Exception as e:
            logger.error(f"Error processing JWT for key: {key_str}. Error: {str(e)}")

    if matching_key:
        return matching_key[len(REDIS_AUTH_KEY_PREFIX) :]
    return None


def delete_user_token_from_redis(
    r: Redis, user_email: str, dry_run: bool = False
) -> bool:
    """
    Scans Redis keys for a user token matching user_email and deletes it if found.
    Returns True if something was deleted, otherwise False.
    """
    user_id, tenant_id = get_user_id(user_email)

    # Scan for keys matching the auth key prefix
    auth_keys = r.scan_iter(f"{REDIS_AUTH_KEY_PREFIX}*", count=SCAN_ITER_COUNT)
    matching_key = None

    for key in auth_keys:
        key_str = key.decode("utf-8")
        jwt_token = r.get(key_str)

        if not jwt_token:
            continue

        try:
            jwt_token_str = (
                jwt_token.decode("utf-8")
                if isinstance(jwt_token, bytes)
                else str(jwt_token)
            )

            if jwt_token_str.startswith("b'") and jwt_token_str.endswith("'"):
                jwt_token_str = jwt_token_str[2:-1]  # Remove b'' wrapper

            jwt_data = json.loads(jwt_token_str)
            if jwt_data.get("tenant_id") == tenant_id and str(
                jwt_data.get("sub")
            ) == str(user_id):
                matching_key = key_str
                break
        except json.JSONDecodeError:
            logger.error(f"Failed to decode JSON for key: {key_str}")
        except Exception as e:
            logger.error(f"Error processing JWT for key: {key_str}. Error: {str(e)}")

    if matching_key:
        if dry_run:
            logger.info(f"(DRY-RUN) Would delete token key: {matching_key}")
        else:
            r.delete(matching_key)
            logger.info(f"Deleted token for user: {user_email}")
        return True
    else:
        logger.info(f"No token found for user: {user_email}")
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Onyx Redis Manager")
    parser.add_argument(
        "--command",
        type=OnyxRedisCommand,
        help="The command to run",
        choices=list(OnyxRedisCommand),
        required=True,
    )

    parser.add_argument(
        "--ssl",
        type=bool,
        default=REDIS_SSL,
        help="Use SSL when connecting to Redis. Usually True for prod and False for local testing",
        required=False,
    )

    parser.add_argument(
        "--host",
        type=str,
        default=REDIS_HOST,
        help="The redis host",
        required=False,
    )

    parser.add_argument(
        "--port",
        type=int,
        default=REDIS_PORT,
        help="The redis port",
        required=False,
    )

    parser.add_argument(
        "--db",
        type=int,
        default=REDIS_DB_NUMBER,
        help="The redis db",
        required=False,
    )

    parser.add_argument(
        "--password",
        type=str,
        default=REDIS_PASSWORD,
        help="The redis password",
        required=False,
    )

    parser.add_argument(
        "--tenant-id",
        type=str,
        help="Tenant ID for get, delete user token, or add to invited users",
        required=False,
    )

    parser.add_argument(
        "--batch",
        type=int,
        default=BATCH_DEFAULT,
        help="Size of operation batches to send to Redis",
        required=False,
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Perform a dry run without actually executing modifications",
        required=False,
    )

    parser.add_argument(
        "--user-email",
        type=str,
        help="User email for get, delete user token, or add to invited users",
        required=False,
    )

    parser.add_argument(
        "--cc-pair",
        type=int,
        help="A connector credential pair id. Used with the purge_deletion_locks command.",
        required=False,
    )

    args = parser.parse_args()

    if args.tenant_id:
        CURRENT_TENANT_ID_CONTEXTVAR.set(args.tenant_id)

    exitcode = onyx_redis(
        command=args.command,
        batch=args.batch,
        dry_run=args.dry_run,
        ssl=args.ssl,
        host=args.host,
        port=args.port,
        db=args.db,
        password=args.password,
        user_email=args.user_email,
        cc_pair_id=args.cc_pair,
    )
    sys.exit(exitcode)
