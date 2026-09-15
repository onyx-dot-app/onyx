"""Runs inside a customer api-server pod, fed to `python -` on stdin.

Takes one argv: a JSON request blob. Writes one sentinel-prefixed JSON line
to stdout. Embedded into the ods binary by impersonate.go.
"""

import json
import os
import secrets
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg2
import redis
from psycopg2 import sql

# Deliberately imports nothing from onyx: this runs against whatever image the
# customer is on, and onyx module paths move between releases. Only the env vars,
# the key prefix, and the token JSON shape are relied on, and those are stable.
RESULT_SENTINEL = "__ONYX_IMPERSONATE_RESULT__"
AUTH_KEY_PREFIX = "fastapi_users_token:"
SCAN_COUNT = 1000


def _schema() -> str:
    return os.environ.get("POSTGRES_DEFAULT_SCHEMA") or "public"


def _redis_client() -> "redis.Redis[Any]":
    kwargs: dict[str, Any] = {
        "host": os.environ.get("REDIS_HOST") or "localhost",
        "port": int(os.environ.get("REDIS_PORT") or 6379),
        "db": int(os.environ.get("REDIS_DB_NUMBER") or 0),
        "password": os.environ.get("REDIS_PASSWORD") or None,
        "decode_responses": True,
    }
    if (os.environ.get("REDIS_SSL") or "").lower() == "true":
        kwargs["ssl"] = True
        kwargs["ssl_cert_reqs"] = os.environ.get("REDIS_SSL_CERT_REQS") or "none"
        ca_certs = os.environ.get("REDIS_SSL_CA_CERTS")
        if ca_certs:
            kwargs["ssl_ca_certs"] = ca_certs
    return redis.Redis(**kwargs)


def _pg_connect() -> Any:
    return psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST") or "127.0.0.1",
        port=os.environ.get("POSTGRES_PORT") or "5432",
        user=os.environ.get("POSTGRES_USER") or "postgres",
        password=os.environ.get("POSTGRES_PASSWORD") or "",
        dbname=os.environ.get("POSTGRES_DB") or "postgres",
    )


def _classify(payload: dict[str, Any]) -> str:
    """Mirrors onyx.auth.session_tokens without importing it, for both formats."""
    if payload.get("logged_out_at"):
        return "terminated"
    if not payload.get("sub"):
        return "malformed"

    expires_at = payload.get("expires_at")
    if not expires_at:
        # Pre-July-2026 tokens carry no expiry; the Redis TTL is their lifetime.
        return "active"
    try:
        if datetime.fromisoformat(expires_at) <= datetime.now(timezone.utc):
            return "expired"
    except ValueError:
        return "malformed"
    return "active"


def _scan_sessions(redis_client: "redis.Redis[Any]") -> list[dict[str, Any]]:
    """Reads every session token, with its status, remaining TTL, and payload."""
    sessions: list[dict[str, Any]] = []
    for key in redis_client.scan_iter(AUTH_KEY_PREFIX + "*", count=SCAN_COUNT):
        raw_value = redis_client.get(key)
        if raw_value is None:
            continue

        try:
            payload = json.loads(raw_value)
        except json.JSONDecodeError:
            payload = {}

        sessions.append(
            {
                "token": key[len(AUTH_KEY_PREFIX) :],
                "sub": payload.get("sub"),
                "status": _classify(payload),
                "ttl_seconds": redis_client.ttl(key),
                "expires_at": payload.get("expires_at"),
                "impersonated_by": payload.get("impersonated_by"),
            }
        )
    return sessions


def _resolve_emails(subs: list[str]) -> dict[str, str]:
    if not subs:
        return {}

    query = sql.SQL('SELECT id, email FROM {}."user" WHERE id::text = ANY(%s)').format(
        sql.Identifier(_schema())
    )
    with _pg_connect() as conn, conn.cursor() as cur:
        cur.execute(query, (subs,))
        return {str(row[0]): row[1] for row in cur.fetchall()}


def _lookup_user(email: str) -> tuple[str, str, str] | None:
    """Returns (id, email, role), matched case-insensitively like get_user_by_email."""
    query = sql.SQL(
        'SELECT id, email, role FROM {}."user" WHERE lower(email) = lower(%s)'
    ).format(sql.Identifier(_schema()))
    with _pg_connect() as conn, conn.cursor() as cur:
        cur.execute(query, (email,))
        row = cur.fetchone()
        return (str(row[0]), row[1], str(row[2])) if row else None


def _mint(request: dict[str, Any]) -> dict[str, Any]:
    email = str(request["email"])
    ttl_seconds = int(request["ttl_seconds"])

    found = _lookup_user(email)
    if found is None:
        return {"ok": False, "error": "No user found with email " + email}
    user_id, actual_email, role = found

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=ttl_seconds)
    # A superset of both formats. Readers before July 2026 take "sub" and ignore
    # the rest; later ones parse the timestamps and drop the unknown marker.
    payload = {
        "sub": user_id,
        "tenant_id": _schema(),
        "issued_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
        "impersonated_by": request["operator"],
    }

    token = secrets.token_urlsafe()
    # TTL matches the logical expiry exactly. Newer deployments would add an hour
    # of grace on top; skipping it keeps the token dead on time on older ones.
    _redis_client().set(AUTH_KEY_PREFIX + token, json.dumps(payload), ex=ttl_seconds)
    return {
        "ok": True,
        "token": token,
        "email": actual_email,
        "user_id": user_id,
        "role": role,
        "expires_at": expires_at.isoformat(),
    }


def _list(_request: dict[str, Any]) -> dict[str, Any]:
    sessions = _scan_sessions(_redis_client())
    emails = _resolve_emails([s["sub"] for s in sessions if s["sub"]])
    for session in sessions:
        session["email"] = emails.get(session["sub"] or "", "<unknown>")
    return {"ok": True, "sessions": sessions}


def _revoke(request: dict[str, Any]) -> dict[str, Any]:
    token = request.get("token")
    include_real_sessions = bool(request.get("include_real_sessions"))

    redis_client = _redis_client()
    if token:
        deleted = redis_client.delete(AUTH_KEY_PREFIX + str(token))
        return {"ok": True, "deleted": int(deleted), "tokens": [token]}

    email = str(request["email"])
    found = _lookup_user(email)
    if found is None:
        return {"ok": False, "error": "No user found with email " + email}
    user_id = found[0]

    revoked: list[str] = []
    for session in _scan_sessions(redis_client):
        if session["sub"] != user_id:
            continue
        if not include_real_sessions and not session["impersonated_by"]:
            continue
        redis_client.delete(AUTH_KEY_PREFIX + session["token"])
        revoked.append(session["token"])

    return {"ok": True, "deleted": len(revoked), "tokens": revoked}


def main() -> int:
    request = json.loads(sys.argv[1])
    command = request["command"]

    handlers = {"mint": _mint, "list": _list, "revoke": _revoke}
    try:
        result = handlers[command](request)
    except Exception as e:
        result = {"ok": False, "error": type(e).__name__ + ": " + str(e)}

    print(RESULT_SENTINEL + json.dumps(result))
    return 0 if result.get("ok") else 1


sys.exit(main())
