"""Seed demo data for manually verifying MCP group/public access control.

Run from backend/ with the worktree env loaded (EE on, DB=onyx_mcpgroup):

    cd backend && set -a && . ../.vscode/.env && set +a && \
        ../.venv/bin/python ../seed_mcp_group_demo.py

Creates: 2 groups, 4 users (known password), a local ollama LLM provider, and
3 MCP servers (1 public, 1 Engineering-only, 1 Sales-only) pointing at the mock
MCP on :8210, each with a few attachable tools. Idempotent by name/email.
"""

from uuid import uuid4

from fastapi_users.password import PasswordHelper
from sqlalchemy import select

from onyx.auth.permissions import Permission
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.enums import MCPServerStatus
from onyx.db.enums import MCPTransport
from onyx.db.llm import upsert_llm_provider
from onyx.db.mcp import create_mcp_server__no_commit
from onyx.db.models import AccountType
from onyx.db.models import Persona
from onyx.db.persona import upsert_persona
from onyx.db.models import MCPAuthenticationType
from onyx.db.models import MCPServer
from onyx.db.models import Tool
from onyx.db.models import User
from onyx.db.models import User__UserGroup
from onyx.db.models import UserGroup
from onyx.db.models import UserRole
from onyx.server.manage.llm.models import LLMProviderUpsertRequest
from onyx.server.manage.llm.models import ModelConfigurationUpsertRequest
from onyx.utils.variable_functionality import fetch_versioned_implementation
from onyx.utils.variable_functionality import set_is_ee_based_on_env_variable

PASSWORD = "Password123!"
MOCK_MCP_URL = "http://localhost:8210/mcp"


def _perms_for_role(role: UserRole) -> list[str]:
    if role == UserRole.ADMIN:
        return [Permission.FULL_ADMIN_PANEL_ACCESS.value]
    return [Permission.BASIC_ACCESS.value]


def get_or_create_user(db, email: str, role: UserRole) -> User:
    user = db.scalar(select(User).where(User.email == email))
    if user:
        # Backfill permissions for users seeded before this fix.
        if not user.effective_permissions:
            user.effective_permissions = _perms_for_role(role)
            db.commit()
        return user
    user = User(
        id=uuid4(),
        email=email,
        hashed_password=PasswordHelper().hash(PASSWORD),
        is_active=True,
        is_superuser=role == UserRole.ADMIN,
        is_verified=True,
        role=role,
        account_type=AccountType.STANDARD,
        effective_permissions=_perms_for_role(role),
    )
    db.add(user)
    db.commit()
    return user


def get_or_create_group(db, name: str) -> UserGroup:
    group = db.scalar(select(UserGroup).where(UserGroup.name == name))
    if group:
        return group
    group = UserGroup(name=name, is_up_to_date=True)
    db.add(group)
    db.commit()
    return group


def ensure_membership(db, user: User, group: UserGroup) -> None:
    existing = db.scalar(
        select(User__UserGroup).where(
            User__UserGroup.user_id == user.id,
            User__UserGroup.user_group_id == group.id,
        )
    )
    if not existing:
        db.add(User__UserGroup(user_id=user.id, user_group_id=group.id))
        db.commit()


def create_mcp(db, name: str, owner: str, is_public: bool, group_ids: list[int]):
    server = db.scalar(select(MCPServer).where(MCPServer.name == name))
    if not server:
        server = create_mcp_server__no_commit(
            owner_email=owner,
            name=name,
            description=f"Demo MCP server ({'public' if is_public else 'restricted'})",
            server_url=MOCK_MCP_URL,
            auth_type=MCPAuthenticationType.NONE,
            transport=MCPTransport.STREAMABLE_HTTP,
            auth_performer=None,
            db_session=db,
            is_public=is_public,
        )
        server.status = MCPServerStatus.CONNECTED
        db.commit()

    make_private = fetch_versioned_implementation(
        "onyx.db.mcp", "make_mcp_server_private"
    )
    server.is_public = is_public
    make_private(
        server_id=server.id,
        user_ids=[],
        group_ids=[] if is_public else group_ids,
        db_session=db,
    )
    db.commit()

    existing_tools = db.scalars(
        select(Tool).where(Tool.mcp_server_id == server.id)
    ).all()
    if not existing_tools:
        for tool_name in ("hello", "tool_1", "tool_2"):
            db.add(
                Tool(
                    name=f"{name}_{tool_name}",
                    display_name=tool_name,
                    description=f"{tool_name} from {name}",
                    mcp_server_id=server.id,
                )
            )
        db.commit()
    return server


def create_agent(db, name: str, owner: User, server: MCPServer) -> None:
    if db.scalar(select(Persona).where(Persona.name == name)):
        return
    tool_ids = [
        t.id
        for t in db.scalars(
            select(Tool).where(Tool.mcp_server_id == server.id)
        ).all()
    ]
    # Admin owner bypasses the MCP access gate; public so it's easy to find.
    upsert_persona(
        user=owner,
        name=name,
        description=f"Demo agent using {server.name}",
        starter_messages=None,
        system_prompt="You are a helpful assistant.",
        task_prompt=None,
        datetime_aware=True,
        is_public=True,
        tool_ids=tool_ids,
        db_session=db,
    )


def seed_llm_provider(db) -> None:
    req = LLMProviderUpsertRequest(
        name="Local Ollama",
        provider="ollama",
        api_base="http://localhost:11434",
        default_model_name="qwen2.5:7b",
        fast_default_model_name="qwen2.5:7b",
        is_public=True,
        model_configurations=[
            ModelConfigurationUpsertRequest(name="qwen2.5:7b", is_visible=True)
        ],
    )
    upsert_llm_provider(req, db)
    db.commit()


def main() -> None:
    # Standalone scripts don't run the app-startup hook, so set the EE flag
    # explicitly or fetch_versioned_implementation resolves the MIT stub.
    set_is_ee_based_on_env_variable()
    SqlEngine.init_engine(pool_size=5, max_overflow=5)
    with get_session_with_current_tenant() as db:
        admin = get_or_create_user(db, "admin@test.local", UserRole.ADMIN)
        alice = get_or_create_user(db, "alice@test.local", UserRole.BASIC)
        bob = get_or_create_user(db, "bob@test.local", UserRole.BASIC)
        carol = get_or_create_user(db, "carol@test.local", UserRole.BASIC)

        engineering = get_or_create_group(db, "Engineering")
        sales = get_or_create_group(db, "Sales")
        ensure_membership(db, alice, engineering)
        ensure_membership(db, bob, sales)
        # carol is intentionally in no group.

        try:
            seed_llm_provider(db)
            llm_note = "Local Ollama (qwen2.5:7b)"
        except Exception as exc:  # noqa: BLE001
            llm_note = f"SKIPPED LLM provider ({exc}); add it in the admin UI"

        public_mcp = create_mcp(db, "Public Weather MCP", admin.email, True, [])
        eng_mcp = create_mcp(
            db, "Engineering MCP", admin.email, False, [engineering.id]
        )
        sales_mcp = create_mcp(db, "Sales MCP", admin.email, False, [sales.id])

        create_agent(db, "Public Helper", admin, public_mcp)
        create_agent(db, "Engineering Helper", admin, eng_mcp)
        create_agent(db, "Sales Helper", admin, sales_mcp)

        print("Seed complete.")
        print(f"  Password for all users: {PASSWORD}")
        print("  admin@test.local  (ADMIN)      -> sees all 3 MCP servers")
        print("  alice@test.local  (Engineering)-> Public + Engineering")
        print("  bob@test.local    (Sales)      -> Public + Sales")
        print("  carol@test.local  (no group)   -> Public only")
        print(f"  LLM provider: {llm_note}")
        print("  Example agents: Public Helper, Engineering Helper, Sales Helper")


if __name__ == "__main__":
    main()
