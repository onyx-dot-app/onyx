import io
from typing import cast

from PIL import Image

from onyx.background.celery.tasks.beat_schedule import CLOUD_BEAT_MULTIPLIER_DEFAULT
from onyx.background.celery.tasks.beat_schedule import (
    CLOUD_DOC_PERMISSION_SYNC_MULTIPLIER_DEFAULT,
)
from onyx.configs.app_configs import ENABLE_TENANT_WORK_GATING
from onyx.configs.app_configs import TENANT_WORK_GATING_FULL_FANOUT_INTERVAL_SECONDS
from onyx.configs.app_configs import TENANT_WORK_GATING_TTL_SECONDS
from onyx.configs.constants import CLOUD_BUILD_FENCE_LOOKUP_TABLE_INTERVAL_DEFAULT
from onyx.configs.constants import ONYX_CLOUD_REDIS_RUNTIME
from onyx.configs.constants import ONYX_CLOUD_TENANT_ID
from onyx.configs.constants import ONYX_EMAILABLE_LOGO_MAX_DIM
from onyx.file_store.file_store import get_default_file_store
from onyx.redis.redis_pool import get_redis_replica_client
from onyx.utils.file import FileWithMimeType
from onyx.utils.file import OnyxStaticFileManager
from onyx.utils.variable_functionality import fetch_ee_implementation_or_noop


class OnyxRuntime:
    """Used by the application to get the final runtime value of a setting.

    Rationale: Settings and overrides may be persisted in multiple places, including the
    DB, Redis, env vars, and default constants, etc. The logic to present a final
    setting to the application should be centralized and in one place.

    Example: To get the logo for the application, one must check the DB for an override,
    use the override if present, fall back to the filesystem if not present, and worry
    about enterprise or not enterprise.
    """

    @staticmethod
    def _get_with_static_fallback(
        db_filename: str | None, static_filename: str
    ) -> FileWithMimeType:
        onyx_file: FileWithMimeType | None = None

        if db_filename:
            file_store = get_default_file_store()
            onyx_file = file_store.get_file_with_mime_type(db_filename)

        if not onyx_file:
            onyx_file = OnyxStaticFileManager.get_static(static_filename)

        if not onyx_file:
            raise RuntimeError(
                f"Resource not found: db={db_filename} static={static_filename}"
            )

        return onyx_file

    @staticmethod
    def get_logo() -> FileWithMimeType:
        STATIC_FILENAME = "static/images/logo.png"

        db_filename: str | None = fetch_ee_implementation_or_noop(
            "onyx.server.enterprise_settings.store", "get_logo_filename", None
        )

        return OnyxRuntime._get_with_static_fallback(db_filename, STATIC_FILENAME)

    @staticmethod
    def get_emailable_logo() -> FileWithMimeType:
        onyx_file = OnyxRuntime.get_logo()

        # check dimensions and resize downwards if necessary or if not PNG
        image = Image.open(io.BytesIO(onyx_file.data))
        if (
            image.size[0] > ONYX_EMAILABLE_LOGO_MAX_DIM
            or image.size[1] > ONYX_EMAILABLE_LOGO_MAX_DIM
            or image.format != "PNG"
        ):
            image.thumbnail(
                (ONYX_EMAILABLE_LOGO_MAX_DIM, ONYX_EMAILABLE_LOGO_MAX_DIM),
                Image.LANCZOS,
            )  # maintains aspect ratio
            output_buffer = io.BytesIO()
            image.save(output_buffer, format="PNG")
            onyx_file = FileWithMimeType(
                data=output_buffer.getvalue(), mime_type="image/png"
            )

        return onyx_file

    @staticmethod
    def get_logotype() -> FileWithMimeType:
        STATIC_FILENAME = "static/images/logotype.png"

        db_filename: str | None = fetch_ee_implementation_or_noop(
            "onyx.server.enterprise_settings.store", "get_logotype_filename", None
        )

        return OnyxRuntime._get_with_static_fallback(db_filename, STATIC_FILENAME)

    @staticmethod
    def get_beat_multiplier() -> float:
        """the beat multiplier is used to scale up or down the frequency of certain beat
        tasks in the cloud. It has a significant effect on load and is useful to adjust
        in real time."""

        beat_multiplier: float = CLOUD_BEAT_MULTIPLIER_DEFAULT

        r = get_redis_replica_client(tenant_id=ONYX_CLOUD_TENANT_ID)

        beat_multiplier_raw = r.get(f"{ONYX_CLOUD_REDIS_RUNTIME}:beat_multiplier")
        if beat_multiplier_raw is not None:
            try:
                beat_multiplier_bytes = cast(bytes, beat_multiplier_raw)
                beat_multiplier = float(beat_multiplier_bytes.decode())
            except ValueError:
                pass

        if beat_multiplier <= 0.0:
            return 1.0

        return beat_multiplier

    @staticmethod
    def get_doc_permission_sync_multiplier() -> float:
        """Permission syncs are a significant source of load / queueing in the cloud."""

        value: float = CLOUD_DOC_PERMISSION_SYNC_MULTIPLIER_DEFAULT

        r = get_redis_replica_client(tenant_id=ONYX_CLOUD_TENANT_ID)

        value_raw = r.get(f"{ONYX_CLOUD_REDIS_RUNTIME}:doc_permission_sync_multiplier")
        if value_raw is not None:
            try:
                value_bytes = cast(bytes, value_raw)
                value = float(value_bytes.decode())
            except ValueError:
                pass

        if value <= 0.0:
            return 1.0

        return value

    @staticmethod
    def _read_tenant_work_gating_flag(axis: str, default: bool) -> bool:
        """Read `runtime:tenant_work_gating:{axis}` from Redis and interpret
        it as a bool. Returns `default` if the key is absent or unparseable.
        `axis` is either `enabled` (compute the gate) or `enforce` (actually
        skip)."""
        r = get_redis_replica_client(tenant_id=ONYX_CLOUD_TENANT_ID)
        raw = r.get(f"{ONYX_CLOUD_REDIS_RUNTIME}:tenant_work_gating:{axis}")
        if raw is None:
            return default

        try:
            return cast(bytes, raw).decode().strip().lower() == "true"
        except Exception:
            return default

    @staticmethod
    def get_tenant_work_gating_enabled() -> bool:
        """Should we *compute* the work gate? (read the Redis set, log how
        many tenants would be skipped). Env-var `ENABLE_TENANT_WORK_GATING`
        is the fallback default when no Redis override is set — it acts as
        the master switch that turns the feature on in shadow mode."""
        return OnyxRuntime._read_tenant_work_gating_flag(
            "enabled", default=ENABLE_TENANT_WORK_GATING
        )

    @staticmethod
    def get_tenant_work_gating_enforce() -> bool:
        """Should we *actually skip* tenants not in the work set?

        Deliberately Redis-only with a hard-coded default of False: the env
        var `ENABLE_TENANT_WORK_GATING` only flips `enabled` (shadow mode),
        never `enforce`. Enforcement has to be turned on by an explicit
        `runtime:tenant_work_gating:enforce=true` write so ops can't
        accidentally skip real tenant traffic by flipping an env flag. Only
        meaningful when `get_tenant_work_gating_enabled()` is also True.
        """
        return OnyxRuntime._read_tenant_work_gating_flag("enforce", default=False)

    @staticmethod
    def get_tenant_work_gating_ttl_seconds() -> int:
        """Membership TTL for the `active_tenants` sorted set. Members older
        than this are treated as "no recent work" by the gate read path.
        Must be > (full-fanout cadence × base task schedule) so self-healing
        has time to refresh memberships before they expire."""
        default = TENANT_WORK_GATING_TTL_SECONDS

        r = get_redis_replica_client(tenant_id=ONYX_CLOUD_TENANT_ID)
        raw = r.get(f"{ONYX_CLOUD_REDIS_RUNTIME}:tenant_work_gating:ttl_seconds")
        if raw is None:
            return default

        try:
            value = int(cast(bytes, raw).decode())
            return value if value > 0 else default
        except ValueError:
            return default

    @staticmethod
    def get_tenant_work_gating_full_fanout_interval_seconds() -> int:
        """Minimum wall-clock interval between full-fanout cycles. When at
        least this many seconds have elapsed since the last bypass, the
        generator ignores the gate on its next invocation and dispatches to
        every non-gated tenant, letting consumers re-populate the active
        set. Schedule-independent so beat drift or backlog can't skew the
        self-heal cadence."""
        default = TENANT_WORK_GATING_FULL_FANOUT_INTERVAL_SECONDS

        r = get_redis_replica_client(tenant_id=ONYX_CLOUD_TENANT_ID)
        raw = r.get(
            f"{ONYX_CLOUD_REDIS_RUNTIME}:tenant_work_gating:full_fanout_interval_seconds"
        )
        if raw is None:
            return default

        try:
            value = int(cast(bytes, raw).decode())
            return value if value > 0 else default
        except ValueError:
            return default

    @staticmethod
    def get_build_fence_lookup_table_interval() -> int:
        """We maintain an active fence table to make lookups of existing fences efficient.
        However, reconstructing the table is expensive, so adjusting it in realtime is useful.
        """

        interval: int = CLOUD_BUILD_FENCE_LOOKUP_TABLE_INTERVAL_DEFAULT

        r = get_redis_replica_client(tenant_id=ONYX_CLOUD_TENANT_ID)

        interval_raw = r.get(
            f"{ONYX_CLOUD_REDIS_RUNTIME}:build_fence_lookup_table_interval"
        )
        if interval_raw is not None:
            try:
                interval_bytes = cast(bytes, interval_raw)
                interval = int(interval_bytes.decode())
            except ValueError:
                pass

        if interval <= 0.0:
            return CLOUD_BUILD_FENCE_LOOKUP_TABLE_INTERVAL_DEFAULT

        return interval
