"""Process management for CLI agent and Next.js server subprocesses."""

import os
import shutil
import signal
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


class ProcessManager:
    """Manages CLI agent and Next.js server subprocess lifecycle.

    Responsible for:
    - Building virtual environment activation settings
    - Starting agent processes with proper environment
    - Starting Next.js dev servers
    - Checking process status
    - Gracefully terminating processes
    """

    def build_venv_env(self, venv_path: Path) -> dict[str, str]:
        """Build environment variables dict with the virtual environment activated.

        Args:
            venv_path: Path to the virtual environment directory

        Returns:
            Environment variables dictionary with venv activated
        """
        env = os.environ.copy()
        venv_bin = str(venv_path / "bin")
        env["PATH"] = f"{venv_bin}:{env.get('PATH', '')}"
        env["VIRTUAL_ENV"] = str(venv_path)
        # Unset PYTHONHOME if set (can interfere with venv)
        env.pop("PYTHONHOME", None)
        return env

    def start_agent_process(
        self,
        sandbox_path: Path,
        agent_command: list[str],
        venv_path: Path | None = None,
        env_vars: dict[str, str] | None = None,
    ) -> subprocess.Popen[str]:
        """Start CLI agent as subprocess.

        Working directory is set to sandbox root.
        Virtual environment is activated if provided.

        Args:
            sandbox_path: Path to the sandbox directory (working dir)
            agent_command: Command and arguments to start the agent
            venv_path: Optional path to virtual environment
            env_vars: Optional additional environment variables

        Returns:
            The subprocess.Popen object for the agent process
        """
        env = self.build_venv_env(venv_path) if venv_path else os.environ.copy()
        if env_vars:
            env.update(env_vars)

        process = subprocess.Popen(
            agent_command,
            cwd=sandbox_path,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return process

    def start_nextjs_server(
        self,
        web_dir: Path,
        port: int,
        timeout: float = 60.0,
    ) -> subprocess.Popen[bytes]:
        """Start Next.js dev server.

        1. Clear .next cache to avoid stale paths from template
        2. Start npm run dev on specified port
        3. Wait for server to be ready

        Args:
            web_dir: Path to the Next.js web directory
            port: Port number to run the server on
            timeout: Maximum time to wait for server to start

        Returns:
            The subprocess.Popen object for the Next.js server

        Raises:
            RuntimeError: If server fails to start within timeout
        """
        # Clear Next.js cache to avoid stale paths from template
        next_cache = web_dir / ".next"
        if next_cache.exists():
            shutil.rmtree(next_cache)

        process = subprocess.Popen(
            ["npm", "run", "dev", "--", "-p", str(port)],
            cwd=web_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Wait for server to be ready
        server_url = f"http://localhost:{port}"
        if not self._wait_for_server(server_url, timeout=timeout):
            # Check if process died
            if process.poll() is not None:
                raise RuntimeError(
                    f"Next.js server process died with code {process.returncode}"
                )
            raise RuntimeError(
                f"Next.js server failed to start within {timeout} seconds"
            )

        return process

    def _wait_for_server(
        self,
        url: str,
        timeout: float = 30.0,
        poll_interval: float = 0.5,
    ) -> bool:
        """Wait for a server to become available by polling.

        Args:
            url: URL to poll
            timeout: Maximum time to wait in seconds
            poll_interval: Time between poll attempts in seconds

        Returns:
            True if server became available, False if timeout reached
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                with urllib.request.urlopen(url, timeout=2) as response:
                    if response.status == 200:
                        return True
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
                pass
            time.sleep(poll_interval)
        return False

    def is_process_running(self, pid: int) -> bool:
        """Check if process with given PID is still running.

        Args:
            pid: Process ID to check

        Returns:
            True if process is running, False otherwise
        """
        try:
            os.kill(pid, 0)  # Signal 0 just checks if process exists
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # Process exists but we can't signal it

    def terminate_process(self, pid: int, timeout: float = 5.0) -> bool:
        """Gracefully terminate process.

        1. Send SIGTERM
        2. Wait up to timeout seconds
        3. If still running, send SIGKILL

        Args:
            pid: Process ID to terminate
            timeout: Maximum time to wait for graceful shutdown

        Returns:
            True if process was terminated, False if it wasn't running
        """
        if not self.is_process_running(pid):
            return False

        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return False

        # Wait for graceful shutdown
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self.is_process_running(pid):
                return True
            time.sleep(0.1)

        # Force kill if still running
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

        return True

    def get_process_info(self, pid: int) -> dict[str, str | int | float] | None:
        """Get information about a running process.

        Uses psutil if available, otherwise returns basic info.

        Args:
            pid: Process ID to get info for

        Returns:
            Dictionary with process info, or None if process not running
        """
        if not self.is_process_running(pid):
            return None

        try:
            import psutil

            proc = psutil.Process(pid)
            return {
                "pid": pid,
                "status": proc.status(),
                "cpu_percent": proc.cpu_percent(),
                "memory_mb": proc.memory_info().rss / 1024 / 1024,
                "create_time": proc.create_time(),
            }
        except ImportError:
            # psutil not available, return basic info
            return {"pid": pid, "status": "unknown"}
        except Exception:
            return {"pid": pid, "status": "unknown"}
