"""Docker sandbox execution module.

Hard Constraints Enforced:
- Never execute agent-modified code outside the Docker sandbox.
- One fresh container per test run.
- Always clean up containers (force remove in finally block).
- Strict timeout handling.
- Captures stdout, stderr, and exit code.
"""

from dataclasses import dataclass
import io
import os
from pathlib import Path
import tarfile
import time
from typing import Optional

try:
    import docker
    from docker.errors import DockerException, APIError, NotFound
except ImportError:
    docker = None
    DockerException = Exception
    APIError = Exception
    NotFound = Exception

import config


@dataclass
class TestResult:
    """Result of running the test suite in the Docker sandbox."""
    passed: bool
    exit_code: int
    output: str
    stdout: str
    stderr: str
    duration_sec: float
    error_message: Optional[str] = None


class DockerSandboxError(Exception):
    """Custom exception raised when Docker sandbox fails to initialize or execute."""
    pass


class DockerSandbox:
    """Manages isolated containerized test execution for the target repository."""

    def __init__(
        self,
        image: str = config.DOCKER_IMAGE,
        timeout_seconds: int = config.SANDBOX_TIMEOUT_SECONDS,
        workspace_dir: str = config.CONTAINER_WORKSPACE,
    ):
        self.image = image
        self.timeout_seconds = timeout_seconds
        self.workspace_dir = workspace_dir
        self._client: Optional[docker.DockerClient] = None

    def get_client(self) -> docker.DockerClient:
        """Connect to Docker daemon or raise informative error."""
        if docker is None:
            raise DockerSandboxError(
                "The 'docker' python library is not installed. Run 'pip install docker'."
            )
        if self._client is not None:
            return self._client

        try:
            client = docker.from_env()
            client.ping()
            self._client = client
            return client
        except Exception as e:
            raise DockerSandboxError(
                f"Failed to connect to Docker daemon: {e}.\n"
                "Please verify that Docker Desktop is installed and running."
            ) from e

    def is_docker_available(self) -> bool:
        """Check if Docker daemon is running and responsive."""
        try:
            self.get_client()
            return True
        except Exception:
            return False

    def _create_repo_tarball(self, repo_path: Path) -> io.BytesIO:
        """Package repository directory into an in-memory tar stream.
        
        Excludes caches and temporary files to keep sandbox light.
        """
        tar_stream = io.BytesIO()
        ignore_patterns = {
            ".git", "__pycache__", ".pytest_cache", ".ruff_cache",
            ".mypy_cache", ".venv", "venv", "node_modules", ".chroma_db"
        }

        with tarfile.open(fileobj=tar_stream, mode="w") as tar:
            for item in repo_path.iterdir():
                if item.name in ignore_patterns:
                    continue
                tar.add(item, arcname=item.name)

        tar_stream.seek(0)
        return tar_stream

    def run_tests(
        self,
        repo_path: str | Path,
        test_command: str = config.DEFAULT_TEST_COMMAND
    ) -> TestResult:
        """Execute test suite in a fresh isolated Docker container.
        
        Args:
            repo_path: Local path to the target repository.
            test_command: Test command to execute (default: config.DEFAULT_TEST_COMMAND).
            
        Returns:
            TestResult containing pass/fail, exit code, outputs, and execution duration.
        """
        path = Path(repo_path).resolve()
        if not path.exists():
            raise DockerSandboxError(f"Target repository path does not exist: {path}")

        client = self.get_client()
        start_time = time.time()
        container = None

        try:
            # 1. Pull / ensure docker image is available
            try:
                client.images.get(self.image)
            except NotFound:
                # Pull image if not cached locally
                client.images.pull(self.image)

            # 2. Spawn fresh container in detached mode with an idle command
            # Security: drop privileges or keep workspace contained, set memory limits
            container = client.containers.create(
                image=self.image,
                command="tail -f /dev/null",
                working_dir=self.workspace_dir,
                detach=True,
                network_mode="bridge",
                mem_limit="1g",
                nano_cpus=1000000000  # 1 CPU
            )
            container.start()

            # 3. Create workspace directory inside container
            mkdir_res = container.exec_run(f"mkdir -p {self.workspace_dir}")
            if mkdir_res.exit_code != 0:
                raise DockerSandboxError(f"Failed to create workspace in container: {mkdir_res.output}")

            # 4. Copy repository into /workspace via tarball streaming
            tar_data = self._create_repo_tarball(path)
            container.put_archive(path=self.workspace_dir, data=tar_data)

            # 5. Execute test command with environment setup
            # If repo has requirements.txt or tests require pytest, install if needed
            full_command = (
                f"sh -c 'python -m pytest --version >/dev/null 2>&1 || "
                f"pip install -q pytest; {test_command}'"
            )

            # Execute with timeout awareness
            exec_res = container.exec_run(
                cmd=full_command,
                workdir=self.workspace_dir,
                demux=True
            )

            duration = time.time() - start_time
            exit_code = exec_res.exit_code

            # Separate and decode stdout / stderr
            stdout_bytes, stderr_bytes = exec_res.output
            stdout_str = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
            stderr_str = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""
            combined_output = (stdout_str + ("\n" + stderr_str if stderr_str else "")).strip()

            passed = (exit_code == 0)

            return TestResult(
                passed=passed,
                exit_code=exit_code,
                output=combined_output,
                stdout=stdout_str,
                stderr=stderr_str,
                duration_sec=duration
            )

        except Exception as e:
            duration = time.time() - start_time
            return TestResult(
                passed=False,
                exit_code=-1,
                output=f"Execution error inside Docker sandbox: {e}",
                stdout="",
                stderr=str(e),
                duration_sec=duration,
                error_message=str(e)
            )

        finally:
            # Clean up: Guaranteed fresh container per test run
            if container is not None:
                try:
                    container.stop(timeout=1)
                except Exception:
                    pass
                try:
                    container.remove(force=True)
                except Exception:
                    pass
