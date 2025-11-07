#!/usr/bin/env python3
"""
Docker Container Management for Onyx Worktrees

Starts, stops, and manages Docker containers for development.
Reads configuration from .vscode/.env file.
"""

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict
from typing import List
from typing import Optional


class Colors:
    GREEN = "\033[0;32m"
    YELLOW = "\033[1;33m"
    RED = "\033[0;31m"
    BLUE = "\033[0;34m"
    NC = "\033[0m"


def load_env_file(env_path: Path) -> Dict[str, str]:
    """Load environment variables from .env file."""
    env_vars = {}
    if not env_path.exists():
        return env_vars

    with open(env_path, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env_vars[key.strip()] = value.strip()

    return env_vars


def run_command(
    cmd: List[str], check: bool = True, capture: bool = False
) -> Optional[subprocess.CompletedProcess]:
    """Run a shell command."""
    try:
        if capture:
            return subprocess.run(cmd, check=check, capture_output=True, text=True)
        else:
            return subprocess.run(cmd, check=check)
    except subprocess.CalledProcessError as e:
        if check:
            raise
        return e


class ContainerManager:
    """Manage Docker containers for Onyx worktree."""

    def __init__(self):
        """Initialize container manager with environment config."""
        # Load .vscode/.env file
        script_dir = Path(__file__).parent
        workspace_root = script_dir.parent.parent
        env_file = workspace_root / ".vscode" / ".env"

        if not env_file.exists():
            print(f"{Colors.RED}ERROR: .vscode/.env file not found!{Colors.NC}")
            print(
                f"{Colors.YELLOW}Please run: python3 scripts/worktree/setup_worktree.py{Colors.NC}"
            )
            sys.exit(1)

        # Load environment variables from file
        env_vars = load_env_file(env_file)

        # Apply to current environment
        for key, value in env_vars.items():
            os.environ[key] = value

        print(f"{Colors.BLUE}Loaded configuration from {env_file}{Colors.NC}")

        # Get configuration with validation
        self.container_prefix = os.getenv("CONTAINER_PREFIX")
        self.worktree_name = os.getenv("WORKTREE_NAME", "")

        # SAFETY CHECK: Prevent destroying main instance containers
        if not self.container_prefix:
            print(
                f"{Colors.RED}ERROR: CONTAINER_PREFIX not set in .vscode/.env{Colors.NC}"
            )
            print(
                f"{Colors.YELLOW}Please run: python3 scripts/worktree/setup_worktree.py{Colors.NC}"
            )
            sys.exit(1)

        if self.container_prefix == "onyx":
            print(
                f"{Colors.RED}ERROR: CONTAINER_PREFIX='onyx' is reserved for main instance!{Colors.NC}"
            )
            print(
                f"{Colors.YELLOW}Worktrees should use a different prefix (e.g., 'onyx_dev1').{Colors.NC}"
            )
            print(
                f"{Colors.YELLOW}Please run: python3 scripts/worktree/setup_worktree.py{Colors.NC}"
            )
            sys.exit(1)

        # Display configuration
        print(f"{Colors.GREEN}Container Prefix: {self.container_prefix}{Colors.NC}")
        if self.worktree_name:
            print(f"{Colors.GREEN}Worktree Name: {self.worktree_name}{Colors.NC}")

        # Port configuration
        self.postgres_port = os.getenv("POSTGRES_PORT", "5432")
        self.redis_port = os.getenv("REDIS_PORT", "6379")
        self.vespa_port = os.getenv("VESPA_PORT", "8081")
        self.vespa_tenant_port = os.getenv("VESPA_TENANT_PORT", "19071")
        self.minio_port = os.getenv("MINIO_PORT", "9004")
        self.minio_console_port = os.getenv("MINIO_CONSOLE_PORT", "9005")

        # Container names
        self.postgres_container = f"{self.container_prefix}_postgres"
        self.redis_container = f"{self.container_prefix}_redis"
        self.vespa_container = f"{self.container_prefix}_vespa"
        self.minio_container = f"{self.container_prefix}_minio"

        # Volume names
        self.postgres_volume = f"{self.container_prefix}_postgres_data"
        self.redis_volume = f"{self.container_prefix}_redis_data"
        self.vespa_volume = f"{self.container_prefix}_vespa_data"
        self.minio_volume = f"{self.container_prefix}_minio_data"

    def stop_containers(self):
        """Stop all containers."""
        print(f"{Colors.YELLOW}Stopping existing containers...{Colors.NC}")
        containers = [
            self.postgres_container,
            self.vespa_container,
            self.redis_container,
            self.minio_container,
        ]

        for container in containers:
            run_command(["docker", "stop", container], check=False, capture=True)
            run_command(["docker", "rm", container], check=False, capture=True)

    def start_postgres(self):
        """Start PostgreSQL container."""
        print(f"{Colors.GREEN}Starting PostgreSQL container...{Colors.NC}")

        cmd = [
            "docker",
            "run",
            "-p",
            f"{self.postgres_port}:5432",
            "--name",
            self.postgres_container,
            "-e",
            "POSTGRES_PASSWORD=password",
            "-d",
            "-v",
            f"{self.postgres_volume}:/var/lib/postgresql/data",
            "postgres",
            "-c",
            "max_connections=250",
        ]

        run_command(cmd)

    def start_vespa(self):
        """Start Vespa container."""
        print(f"{Colors.GREEN}Starting Vespa container...{Colors.NC}")

        cmd = [
            "docker",
            "run",
            "--detach",
            "--name",
            self.vespa_container,
            "--hostname",
            "vespa-container",
            "--publish",
            f"{self.vespa_port}:8081",
            "--publish",
            f"{self.vespa_tenant_port}:19071",
            "-v",
            f"{self.vespa_volume}:/opt/vespa/var",
            "vespaengine/vespa:8",
        ]

        run_command(cmd)

    def start_redis(self):
        """Start Redis container."""
        print(f"{Colors.GREEN}Starting Redis container...{Colors.NC}")

        cmd = [
            "docker",
            "run",
            "--detach",
            "--name",
            self.redis_container,
            "--publish",
            f"{self.redis_port}:6379",
            "-v",
            f"{self.redis_volume}:/data",
            "redis",
        ]

        run_command(cmd)

    def start_minio(self):
        """Start MinIO container."""
        print(f"{Colors.GREEN}Starting MinIO container...{Colors.NC}")

        cmd = [
            "docker",
            "run",
            "--detach",
            "--name",
            self.minio_container,
            "--publish",
            f"{self.minio_port}:9000",
            "--publish",
            f"{self.minio_console_port}:9001",
            "-e",
            "MINIO_ROOT_USER=minioadmin",
            "-e",
            "MINIO_ROOT_PASSWORD=minioadmin",
            "-v",
            f"{self.minio_volume}:/data",
            "minio/minio",
            "server",
            "/data",
            "--console-address",
            ":9001",
        ]

        run_command(cmd)

    def run_migrations(self):
        """Run Alembic migrations."""
        print(f"{Colors.GREEN}Running Alembic migration...{Colors.NC}")

        # Give Postgres a moment to start
        print(f"{Colors.YELLOW}Waiting for PostgreSQL to be ready...{Colors.NC}")
        time.sleep(3)

        # Find backend directory
        script_dir = Path(__file__).parent
        workspace_root = script_dir.parent.parent
        backend_dir = workspace_root / "backend"

        if backend_dir.exists():
            original_dir = Path.cwd()
            try:
                os.chdir(backend_dir)
                run_command(["alembic", "upgrade", "head"])
            finally:
                os.chdir(original_dir)
        else:
            print(
                f"{Colors.YELLOW}Backend directory not found, skipping migrations{Colors.NC}"
            )

    def print_summary(self):
        """Print summary of configuration and next steps."""
        # Get application ports
        port = os.getenv("PORT", "3000")
        app_port = os.getenv("APP_PORT", "8080")
        model_server_port = os.getenv("MODEL_SERVER_PORT", "9000")
        slack_bot_metrics_port = os.getenv("SLACK_BOT_METRICS_PORT", "8000")

        print()
        print(f"{Colors.BLUE}{'='*60}{Colors.NC}")
        print(f"{Colors.GREEN}Onyx Worktree Containers Started{Colors.NC}")
        print(f"{Colors.BLUE}{'='*60}{Colors.NC}")
        print()

        if self.worktree_name:
            print(f"{Colors.YELLOW}Worktree:{Colors.NC} {self.worktree_name}")
        print(f"{Colors.YELLOW}Container Prefix:{Colors.NC} {self.container_prefix}")
        print()

        print(f"{Colors.BLUE}Application Ports:{Colors.NC}")
        print(f"  Next.js Web:       http://localhost:{port}")
        print(f"  API Server:        http://localhost:{app_port}")
        print(f"  Model Server:      http://localhost:{model_server_port}")
        print(f"  Slack Bot Metrics: http://localhost:{slack_bot_metrics_port}")
        print()

        print(f"{Colors.BLUE}Infrastructure Ports:{Colors.NC}")
        print(f"  PostgreSQL:        localhost:{self.postgres_port}")
        print(f"  Redis:             localhost:{self.redis_port}")
        print(f"  Vespa:             http://localhost:{self.vespa_port}")
        print(f"  Vespa Tenant:      http://localhost:{self.vespa_tenant_port}")
        print(f"  MinIO API:         http://localhost:{self.minio_port}")
        print(f"  MinIO Console:     http://localhost:{self.minio_console_port}")
        print()

        print(f"{Colors.BLUE}Running Containers:{Colors.NC}")
        print(f"  {self.postgres_container}")
        print(f"  {self.redis_container}")
        print(f"  {self.vespa_container}")
        print(f"  {self.minio_container}")
        print()

        print(f"{Colors.GREEN}Next Steps:{Colors.NC}")
        print("  1. Open VSCode Run & Debug panel (Cmd+Shift+D)")
        print('  2. Select "Run All Onyx Services"')
        print("  3. Click Start")
        print(f"  4. Access application at http://localhost:{port}")
        print()
        print(f"{Colors.BLUE}{'='*60}{Colors.NC}")
        print()

    def start_all(self):
        """Start all containers."""
        try:
            self.stop_containers()
            self.start_postgres()
            self.start_vespa()
            self.start_redis()
            self.start_minio()
            self.run_migrations()

            self.print_summary()

        except subprocess.CalledProcessError as e:
            print(f"{Colors.RED}Error starting containers: {e}{Colors.NC}")
            self.stop_containers()
            raise


def main():
    """Main entry point."""
    manager = ContainerManager()
    manager.start_all()


if __name__ == "__main__":
    main()
