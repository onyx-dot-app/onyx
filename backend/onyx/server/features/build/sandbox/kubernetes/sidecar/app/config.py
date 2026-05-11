from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration sourced from env vars (prefix SIDECAR_)."""

    model_config = SettingsConfigDict(env_prefix="SIDECAR_", env_file=None)

    host: str = (
        "0.0.0.0"  # noqa: S104 — listening on all interfaces is correct inside a pod
    )
    port: int = 8080

    workspace_root: Path = Path("/workspace")

    auth_token: str | None = None
    auth_token_file: Path | None = None

    idle_timeout_seconds: int = 3600
    idle_check_interval_seconds: int = 30

    max_read_bytes: int = 100 * 1024 * 1024  # 100 MiB
    max_write_bytes: int = 100 * 1024 * 1024
    max_exec_output_bytes: int = 10 * 1024 * 1024  # 10 MiB per stream (stdout, stderr)
    exec_default_timeout_seconds: int = 30
    exec_max_timeout_seconds: int = 300

    log_level: str = "INFO"

    def load_auth_token(self) -> str:
        """Resolve the auth token from either env var or mounted file.

        Failing to set one or the other is a configuration error — we refuse to
        run without auth rather than silently disabling it.
        """
        if self.auth_token:
            return self.auth_token
        if self.auth_token_file:
            # No exists() guard: the file can vanish between check and read
            # (secret rotation, projected-volume remount). Chain the OSError
            # into the RuntimeError so the original cause shows up in the
            # server log when auth.py converts this to a 503.
            try:
                token = self.auth_token_file.read_text().strip()
                if token:
                    return token
            except OSError as exc:
                raise RuntimeError(
                    f"Auth token file {self.auth_token_file} is unreadable: {exc}",
                ) from exc
        raise RuntimeError(
            "Sidecar auth token is not configured. "
            "Set SIDECAR_AUTH_TOKEN or mount a token file at SIDECAR_AUTH_TOKEN_FILE.",
        )


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings_for_tests() -> None:
    """Test-only: drop the cached Settings so a new instance can be constructed."""
    global _settings
    _settings = None
