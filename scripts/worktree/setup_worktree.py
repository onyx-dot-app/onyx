#!/usr/bin/env python3
"""
Onyx Worktree Setup Script

Automatically configures a worktree for local development with dynamic port allocation.

Usage:
    python scripts/worktree/setup_worktree.py
"""

import os
import socket
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict


# ANSI color codes
class Colors:
    GREEN = "\033[0;32m"
    YELLOW = "\033[1;33m"
    RED = "\033[0;31m"
    NC = "\033[0m"  # No Color


def print_header(text: str):
    """Print colored header."""
    print(f"{Colors.GREEN}=== {text} ==={Colors.NC}")


def print_step(text: str):
    """Print step message."""
    print(f"\n{Colors.GREEN}{text}{Colors.NC}")


def print_substep(text: str):
    """Print sub-step message."""
    print(f"{Colors.YELLOW}{text}{Colors.NC}")


def print_error(text: str):
    """Print error message."""
    print(f"{Colors.RED}ERROR: {text}{Colors.NC}")


def is_port_available(port: int) -> bool:
    """Check if a port is available for binding."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("localhost", port))
            return True
        except OSError:
            return False


def find_available_port(
    base_port: int, service_name: str, increment: int = 10, max_attempts: int = 20
) -> int:
    """Find next available port starting from base_port."""
    print_substep(f"Finding available port for {service_name} (base: {base_port})...")

    for i in range(max_attempts):
        port = base_port + (i * increment)
        if is_port_available(port):
            print(f"{Colors.GREEN}  ✓ Found: {port}{Colors.NC}")
            return port
        else:
            print(f"  ✗ Port {port} in use, trying next...")

    raise RuntimeError(f"Could not find available port for {service_name}")


def get_worktree_name() -> str:
    """Detect worktree name from directory."""
    workspace_root = Path(__file__).parent.parent.parent.absolute()
    return workspace_root.name


def load_existing_env_settings(workspace_root: Path) -> Dict[str, str]:
    """
    Load existing .env settings from current worktree or main repo.

    Priority:
    1. Current worktree .vscode/.env (if exists)
    2. Main repo .vscode/.env (if exists)
    3. Empty dict (no existing settings)

    Returns only non-port-related settings to preserve.
    """
    # Variables that should NOT be preserved (will be regenerated)
    EXCLUDED_VARS = {
        "PORT",
        "APP_PORT",
        "MODEL_SERVER_PORT",
        "SLACK_BOT_METRICS_PORT",
        "POSTGRES_PORT",
        "REDIS_PORT",
        "VESPA_PORT",
        "VESPA_TENANT_PORT",
        "MINIO_PORT",
        "MINIO_CONSOLE_PORT",
        "WEB_DOMAIN",
        "INTERNAL_URL",
        "S3_ENDPOINT_URL",
        "WORKTREE_NAME",
        "CONTAINER_PREFIX",
        "INDEXING_MODEL_SERVER_PORT",  # Derived from MODEL_SERVER_PORT
    }

    existing_settings = {}

    # Try current worktree .env first
    current_env = workspace_root / ".vscode" / ".env"

    # Try main repo .env as fallback
    main_repo_env = workspace_root.parent.parent / "onyx" / ".vscode" / ".env"

    env_file_to_load = None
    if current_env.exists():
        env_file_to_load = current_env
        print(f"  Loading existing settings from: {current_env}")
    elif main_repo_env.exists():
        env_file_to_load = main_repo_env
        print(f"  Loading settings from main repo: {main_repo_env}")

    if env_file_to_load:
        with open(env_file_to_load, "r") as f:
            for line in f:
                line = line.strip()
                # Skip comments and empty lines
                if not line or line.startswith("#"):
                    continue

                # Parse KEY=VALUE
                if "=" in line:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip()

                    # Only preserve non-port-related settings
                    if key not in EXCLUDED_VARS and value:
                        existing_settings[key] = value

        print(f"  Preserved {len(existing_settings)} settings from existing .env")
    else:
        print("  No existing .env found, using defaults")

    return existing_settings


def allocate_ports() -> Dict[str, int]:
    """Allocate ports for all services."""
    print_step("Step 1: Finding available ports...")

    ports = {
        "PORT": find_available_port(3000, "Next.js Web"),
        "APP_PORT": find_available_port(8080, "API Server"),
        "MODEL_SERVER_PORT": find_available_port(9000, "Model Server"),
        "SLACK_BOT_METRICS_PORT": find_available_port(8000, "Slack Bot Metrics"),
        "POSTGRES_PORT": find_available_port(5432, "PostgreSQL"),
        "REDIS_PORT": find_available_port(6379, "Redis"),
        "VESPA_PORT": find_available_port(8081, "Vespa"),
        "VESPA_TENANT_PORT": find_available_port(19071, "Vespa Tenant"),
        "MINIO_PORT": find_available_port(9004, "MinIO API"),
        "MINIO_CONSOLE_PORT": find_available_port(9005, "MinIO Console"),
    }

    return ports


def generate_env_file(
    worktree_name: str,
    ports: Dict[str, int],
    workspace_root: Path,
    existing_settings: Dict[str, str],
):
    """Generate .vscode/.env file, preserving existing non-port settings."""
    print_step("Step 2: Generating .vscode/.env...")

    vscode_dir = workspace_root / ".vscode"
    vscode_dir.mkdir(exist_ok=True)

    # Helper function to get value from existing settings or use default
    def get_setting(key: str, default: str) -> str:
        return existing_settings.get(key, default)

    env_content = f"""##################################################
# AUTO-GENERATED WORKTREE CONFIGURATION
# Worktree: {worktree_name}
# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
##################################################
#
# This file was auto-generated by scripts/setup_worktree.py
# Ports were dynamically allocated to avoid conflicts.
# Non-port settings were preserved from existing configuration.
#
# To regenerate: python scripts/setup_worktree.py
##################################################

#####
# Application Ports (DYNAMICALLY ALLOCATED)
#####
# Next.js web server
PORT={ports['PORT']}
# Frontend URL
WEB_DOMAIN=http://localhost:{ports['PORT']}
# Backend URL (for Next.js rewrites)
INTERNAL_URL=http://localhost:{ports['APP_PORT']}
# API Server (FastAPI)
APP_PORT={ports['APP_PORT']}
# Model Server (FastAPI)
MODEL_SERVER_PORT={ports['MODEL_SERVER_PORT']}
# Slack Bot Prometheus metrics port
SLACK_BOT_METRICS_PORT={ports['SLACK_BOT_METRICS_PORT']}

# Development features
UVICORN_RELOAD={get_setting('UVICORN_RELOAD', 'true')}

#####
# Infrastructure - PostgreSQL (DYNAMICALLY ALLOCATED PORTS)
#####
POSTGRES_HOST={get_setting('POSTGRES_HOST', 'localhost')}
POSTGRES_PORT={ports['POSTGRES_PORT']}
POSTGRES_USER={get_setting('POSTGRES_USER', 'postgres')}
POSTGRES_PASSWORD={get_setting('POSTGRES_PASSWORD', 'password')}
POSTGRES_DB={get_setting('POSTGRES_DB', 'postgres')}

#####
# Infrastructure - Redis (DYNAMICALLY ALLOCATED PORTS)
#####
REDIS_HOST={get_setting('REDIS_HOST', 'localhost')}
REDIS_PORT={ports['REDIS_PORT']}
REDIS_PASSWORD={get_setting('REDIS_PASSWORD', '')}
REDIS_DB_NUMBER={get_setting('REDIS_DB_NUMBER', '0')}
REDIS_DB_NUMBER_CELERY={get_setting('REDIS_DB_NUMBER_CELERY', '15')}
REDIS_DB_NUMBER_CELERY_RESULT_BACKEND={get_setting('REDIS_DB_NUMBER_CELERY_RESULT_BACKEND', '14')}

#####
# Infrastructure - Vespa (DYNAMICALLY ALLOCATED PORTS)
#####
VESPA_HOST={get_setting('VESPA_HOST', 'localhost')}
VESPA_PORT={ports['VESPA_PORT']}
VESPA_TENANT_PORT={ports['VESPA_TENANT_PORT']}

#####
# Infrastructure - MinIO (S3) (DYNAMICALLY ALLOCATED PORTS)
#####
MINIO_PORT={ports['MINIO_PORT']}
MINIO_CONSOLE_PORT={ports['MINIO_CONSOLE_PORT']}
S3_ENDPOINT_URL=http://localhost:{ports['MINIO_PORT']}
S3_FILE_STORE_BUCKET_NAME={get_setting('S3_FILE_STORE_BUCKET_NAME', 'onyx-file-store-bucket')}
S3_AWS_ACCESS_KEY_ID={get_setting('S3_AWS_ACCESS_KEY_ID', 'minioadmin')}
S3_AWS_SECRET_ACCESS_KEY={get_setting('S3_AWS_SECRET_ACCESS_KEY', 'minioadmin')}

#####
# Service Communication
#####
MODEL_SERVER_HOST={get_setting('MODEL_SERVER_HOST', 'localhost')}
INDEXING_MODEL_SERVER_HOST={get_setting('INDEXING_MODEL_SERVER_HOST', 'localhost')}
INDEXING_MODEL_SERVER_PORT={ports['MODEL_SERVER_PORT']}

#####
# Container Configuration
# Container names: onyx_{worktree_name}_<service>
# Volumes: onyx_{worktree_name}_<service>_data
#####
WORKTREE_NAME={worktree_name}
CONTAINER_PREFIX=onyx_{worktree_name}

#####
# Development Settings (PRESERVED FROM EXISTING CONFIG)
#####
AUTH_TYPE={get_setting('AUTH_TYPE', 'basic')}
SKIP_WARM_UP={get_setting('SKIP_WARM_UP', 'True')}
LOG_ONYX_MODEL_INTERACTIONS={get_setting('LOG_ONYX_MODEL_INTERACTIONS', 'True')}
LOG_LEVEL={get_setting('LOG_LEVEL', 'debug')}
DISABLE_LLM_DOC_RELEVANCE={get_setting('DISABLE_LLM_DOC_RELEVANCE', 'False')}

# Cloud UI
NEXT_PUBLIC_CLOUD_ENABLED={get_setting('NEXT_PUBLIC_CLOUD_ENABLED', 'true')}

# Enterprise Features
ENABLE_PAID_ENTERPRISE_EDITION_FEATURES={get_setting('ENABLE_PAID_ENTERPRISE_EDITION_FEATURES', 'true')}
ENABLE_PERMISSION_SYNC={get_setting('ENABLE_PERMISSION_SYNC', 'true')}
NEXT_PUBLIC_ENABLE_PAID_EE_FEATURES={get_setting('NEXT_PUBLIC_ENABLE_PAID_EE_FEATURES', 'true')}

# Email verification
REQUIRE_EMAIL_VERIFICATION={get_setting('REQUIRE_EMAIL_VERIFICATION', 'False')}

# Extra connectors
SHOW_EXTRA_CONNECTORS={get_setting('SHOW_EXTRA_CONNECTORS', 'True')}

# Python
PYTHONPATH={get_setting('PYTHONPATH', '../backend')}
PYTHONUNBUFFERED={get_setting('PYTHONUNBUFFERED', '1')}

#####
# API Keys & Model Configuration (PRESERVED FROM EXISTING CONFIG)
#####
"""

    # Add preserved API keys and model settings
    api_key_vars = [
        "GEN_AI_API_KEY",
        "OPENAI_API_KEY",
        "GEN_AI_MODEL_VERSION",
        "FAST_GEN_AI_MODEL_VERSION",
        "EXA_API_KEY",
        "LANGSMITH_API_KEY",
        "LANGSMITH_PROJECT",
        "LANGSMITH_ENDPOINT",
        "LANGSMITH_TRACING",
    ]

    for var in api_key_vars:
        if var in existing_settings:
            env_content += f"{var}={existing_settings[var]}\n"

    # Add agent search configs
    env_content += f"""
# Agent Search configs
AGENT_RETRIEVAL_STATS={get_setting('AGENT_RETRIEVAL_STATS', 'False')}
AGENT_RERANKING_STATS={get_setting('AGENT_RERANKING_STATS', 'True')}
AGENT_MAX_QUERY_RETRIEVAL_RESULTS={get_setting('AGENT_MAX_QUERY_RETRIEVAL_RESULTS', '20')}
AGENT_RERANKING_MAX_QUERY_RETRIEVAL_RESULTS={get_setting('AGENT_RERANKING_MAX_QUERY_RETRIEVAL_RESULTS', '20')}

#####
# Additional Settings (PRESERVED FROM EXISTING CONFIG)
#####
"""

    # Add any other settings that weren't already included
    included_vars = {
        "PORT",
        "WEB_DOMAIN",
        "INTERNAL_URL",
        "APP_PORT",
        "MODEL_SERVER_PORT",
        "UVICORN_RELOAD",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "REDIS_HOST",
        "REDIS_PORT",
        "REDIS_PASSWORD",
        "REDIS_DB_NUMBER",
        "REDIS_DB_NUMBER_CELERY",
        "REDIS_DB_NUMBER_CELERY_RESULT_BACKEND",
        "VESPA_HOST",
        "VESPA_PORT",
        "VESPA_TENANT_PORT",
        "MINIO_PORT",
        "MINIO_CONSOLE_PORT",
        "S3_ENDPOINT_URL",
        "S3_FILE_STORE_BUCKET_NAME",
        "S3_AWS_ACCESS_KEY_ID",
        "S3_AWS_SECRET_ACCESS_KEY",
        "MODEL_SERVER_HOST",
        "INDEXING_MODEL_SERVER_HOST",
        "INDEXING_MODEL_SERVER_PORT",
        "WORKTREE_NAME",
        "CONTAINER_PREFIX",
        "AUTH_TYPE",
        "SKIP_WARM_UP",
        "LOG_ONYX_MODEL_INTERACTIONS",
        "LOG_LEVEL",
        "DISABLE_LLM_DOC_RELEVANCE",
        "NEXT_PUBLIC_CLOUD_ENABLED",
        "ENABLE_PAID_ENTERPRISE_EDITION_FEATURES",
        "ENABLE_PERMISSION_SYNC",
        "NEXT_PUBLIC_ENABLE_PAID_EE_FEATURES",
        "REQUIRE_EMAIL_VERIFICATION",
        "SHOW_EXTRA_CONNECTORS",
        "PYTHONPATH",
        "PYTHONUNBUFFERED",
        "AGENT_RETRIEVAL_STATS",
        "AGENT_RERANKING_STATS",
        "AGENT_MAX_QUERY_RETRIEVAL_RESULTS",
        "AGENT_RERANKING_MAX_QUERY_RETRIEVAL_RESULTS",
        *api_key_vars,
    }

    for key, value in existing_settings.items():
        if key not in included_vars:
            env_content += f"{key}={value}\n"

    env_file = vscode_dir / ".env"
    env_file.write_text(env_content)
    print(f"{Colors.GREEN}  ✓ Created .vscode/.env{Colors.NC}")

    if existing_settings:
        print(
            f"{Colors.GREEN}  ✓ Preserved {len(existing_settings)} settings from existing config{Colors.NC}"
        )


def create_web_env_symlink(workspace_root: Path):
    """Create symlink from web/.env to .vscode/.env for Next.js."""
    print_step("Step 2b: Creating web/.env symlink...")

    web_dir = workspace_root / "web"
    web_env = web_dir / ".env"
    vscode_env = workspace_root / ".vscode" / ".env"

    # Remove existing symlink or file
    if web_env.exists() or web_env.is_symlink():
        web_env.unlink()

    # Create relative symlink
    web_env.symlink_to(os.path.relpath(vscode_env, web_dir))
    print(f"{Colors.GREEN}  ✓ Created symlink: web/.env -> ../.vscode/.env{Colors.NC}")


def generate_launch_json(ports: Dict[str, int], workspace_root: Path):
    """Generate .vscode/launch.json from template."""
    print_step("Step 3: Generating .vscode/launch.json from template...")

    template_path = workspace_root / ".vscode" / "launch.template.jsonc"

    if not template_path.exists():
        print_error(f"Template not found at {template_path}")
        print(
            f"{Colors.YELLOW}Skipping launch.json generation. Run this script again after creating the template.{Colors.NC}"
        )
        return

    # Read template
    with open(template_path, "r") as f:
        content = f.read()

    # Remove JSONC comments while preserving // in strings (like http://)
    lines = content.split("\n")
    json_lines = []
    for line in lines:
        # Remove inline comments but preserve strings with //
        if "//" in line:
            # Find // that's not inside a string
            in_string = False
            escape_next = False
            comment_pos = -1

            for i, char in enumerate(line):
                if escape_next:
                    escape_next = False
                    continue

                if char == "\\":
                    escape_next = True
                    continue

                if char == '"':
                    in_string = not in_string
                    continue

                # Check for // outside of strings
                if (
                    not in_string
                    and char == "/"
                    and i + 1 < len(line)
                    and line[i + 1] == "/"
                ):
                    comment_pos = i
                    break

            # Remove comment if found
            if comment_pos >= 0:
                stripped = line[:comment_pos].rstrip()
                if stripped:
                    json_lines.append(stripped)
            else:
                json_lines.append(line)
        else:
            json_lines.append(line)

    content = "\n".join(json_lines)

    # Replace placeholders
    content = content.replace("${PORT}", str(ports["PORT"]))
    content = content.replace("${APP_PORT}", str(ports["APP_PORT"]))
    content = content.replace("${MODEL_SERVER_PORT}", str(ports["MODEL_SERVER_PORT"]))

    # Write launch.json
    launch_file = workspace_root / ".vscode" / "launch.json"
    launch_file.write_text(content)
    print(f"{Colors.GREEN}  ✓ Generated .vscode/launch.json{Colors.NC}")


def print_summary(worktree_name: str, ports: Dict[str, int]):
    """Print setup summary."""
    print()
    print_header("Setup Complete!")
    print()
    print(f"Worktree: {worktree_name}")
    print(f"Container prefix: onyx_{worktree_name}")
    print()
    print("Allocated Ports:")
    print(f"  Web:       {ports['PORT']}")
    print(f"  API:       {ports['APP_PORT']}")
    print(f"  Model:     {ports['MODEL_SERVER_PORT']}")
    print(f"  Postgres:  {ports['POSTGRES_PORT']}")
    print(f"  Redis:     {ports['REDIS_PORT']}")
    print(f"  Vespa:     {ports['VESPA_PORT']}")
    print(f"  MinIO:     {ports['MINIO_PORT']}")
    print()
    print("Next Steps:")
    print("  1. Review/edit .vscode/.env (add API keys, etc.)")
    print("  2. Start containers: python .vscode/start_containers.py")
    print("  3. Launch services from VSCode: 'Run All Onyx Services'")
    print()


def main():
    """Main setup function."""
    try:
        print_header("Onyx Worktree Setup")
        print()

        # Detect worktree
        worktree_name = get_worktree_name()
        workspace_root = Path(__file__).parent.parent.parent.absolute()

        print(f"Workspace: {workspace_root}")
        print(f"Worktree name: {worktree_name}")
        print()

        # Load existing settings (from current worktree or main repo)
        existing_settings = load_existing_env_settings(workspace_root)

        # Allocate ports
        ports = allocate_ports()

        # Generate files
        generate_env_file(worktree_name, ports, workspace_root, existing_settings)
        create_web_env_symlink(workspace_root)
        generate_launch_json(ports, workspace_root)

        # Print summary
        print_summary(worktree_name, ports)

    except Exception as e:
        print_error(str(e))
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
