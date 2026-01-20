"""Process management for CLI agent and Next.js server subprocesses."""

import os
import shutil
import signal
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from onyx.utils.logger import setup_logger

logger = setup_logger()


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
        logger.info(f"Starting Next.js server in {web_dir} on port {port}")

        # Clear Next.js cache to avoid stale paths from template
        next_cache = web_dir / ".next"
        if next_cache.exists():
            logger.debug(f"Clearing Next.js cache at {next_cache}")
            shutil.rmtree(next_cache)

        # Verify web_dir exists and has package.json
        if not web_dir.exists():
            logger.error(f"Web directory does not exist: {web_dir}")
            raise RuntimeError(f"Web directory does not exist: {web_dir}")

        package_json = web_dir / "package.json"
        if not package_json.exists():
            logger.error(f"package.json not found in {web_dir}")
            raise RuntimeError(f"package.json not found in {web_dir}")

        logger.debug(f"Starting npm run dev command in {web_dir}")
        process = subprocess.Popen(
            ["npm", "run", "dev", "--", "-p", str(port)],
            cwd=web_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        logger.info(f"Next.js process started with PID {process.pid}")

        # Wait for server to be ready
        server_url = f"http://localhost:{port}"
        logger.info(f"Waiting for Next.js server at {server_url} (timeout: {timeout}s)")

        if not self._wait_for_server(server_url, timeout=timeout, process=process):
            # Check if process died
            if process.poll() is not None:
                # Capture stdout/stderr for debugging
                stdout_data = b""
                stderr_data = b""
                try:
                    # Read available output (non-blocking since process is dead)
                    if process.stdout:
                        stdout_data = process.stdout.read()
                    if process.stderr:
                        stderr_data = process.stderr.read()
                except Exception as e:
                    logger.warning(f"Failed to read process output: {e}")

                stdout_str = stdout_data.decode("utf-8", errors="replace")
                stderr_str = stderr_data.decode("utf-8", errors="replace")

                logger.error(
                    f"Next.js server process died with code {process.returncode}"
                )
                if stdout_str.strip():
                    logger.error(f"Next.js stdout:\n{stdout_str}")
                if stderr_str.strip():
                    logger.error(f"Next.js stderr:\n{stderr_str}")

                raise RuntimeError(
                    f"Next.js server process died with code {process.returncode}. "
                    f"stderr: {stderr_str[:500]}"
                )

            # Process still running but server not responding
            logger.error(
                f"Next.js server failed to respond within {timeout} seconds "
                f"(process still running with PID {process.pid})"
            )
            # Try to get any available output
            try:
                if process.stdout:
                    stdout_data = process.stdout.read1(4096)  # type: ignore
                    if stdout_data:
                        logger.error(
                            f"Partial stdout: {stdout_data.decode('utf-8', errors='replace')}"
                        )
            except Exception:
                pass

            raise RuntimeError(
                f"Next.js server failed to start within {timeout} seconds"
            )

        logger.info(f"Next.js server is ready at {server_url}")
        return process

    def _wait_for_server(
        self,
        url: str,
        timeout: float = 30.0,
        poll_interval: float = 0.5,
        process: subprocess.Popen[bytes] | None = None,
    ) -> bool:
        """Wait for a server to become available by polling.

        Args:
            url: URL to poll
            timeout: Maximum time to wait in seconds
            poll_interval: Time between poll attempts in seconds
            process: Optional process to check if it's still running

        Returns:
            True if server became available, False if timeout reached
        """
        start_time = time.time()
        attempt_count = 0
        last_log_time = start_time

        while time.time() - start_time < timeout:
            attempt_count += 1
            elapsed = time.time() - start_time

            # Check if process died early
            if process is not None and process.poll() is not None:
                logger.warning(
                    f"Process died during wait (exit code: {process.returncode}) "
                    f"after {elapsed:.1f}s and {attempt_count} attempts"
                )
                return False

            try:
                with urllib.request.urlopen(url, timeout=2) as response:
                    if response.status == 200:
                        logger.debug(
                            f"Server ready after {elapsed:.1f}s and {attempt_count} attempts"
                        )
                        return True
            except urllib.error.HTTPError as e:
                # Log HTTP errors (server responding but with error)
                if time.time() - last_log_time >= 10:
                    logger.debug(
                        f"HTTP error {e.code} from {url} after {elapsed:.1f}s "
                        f"({attempt_count} attempts)"
                    )
                    last_log_time = time.time()
            except (urllib.error.URLError, TimeoutError) as e:
                # Log connection errors periodically (every 10 seconds)
                if time.time() - last_log_time >= 10:
                    logger.debug(
                        f"Still waiting for {url} after {elapsed:.1f}s "
                        f"({attempt_count} attempts): {type(e).__name__}"
                    )
                    last_log_time = time.time()

            time.sleep(poll_interval)

        logger.warning(
            f"Server at {url} did not become available within {timeout}s "
            f"({attempt_count} attempts)"
        )
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
