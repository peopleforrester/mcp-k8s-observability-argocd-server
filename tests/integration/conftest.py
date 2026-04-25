# ABOUTME: Shared pytest fixtures and helpers for integration tests
# ABOUTME: Provides Kind/ArgoCD detection, port-forward, and connection setup

"""Shared pytest fixtures for the integration suite.

Anything used by more than one integration test file lives here so pytest's
fixture-resolution discovers it via conftest (the only mechanism that works
across files). Per-file fixtures stay in their respective test modules.
"""

from __future__ import annotations

import base64
import os
import signal
import socket
import subprocess
import time
from typing import TYPE_CHECKING

import pytest
from pydantic import SecretStr

from argocd_mcp.config import ArgocdInstance

if TYPE_CHECKING:
    from collections.abc import Iterator


def _kubectl_context() -> str:
    """Return the kubectl context to use for tests."""
    return os.environ.get("TEST_K8S_CONTEXT", "kind-argocd-mcp-test")


def _is_argocd_available() -> bool:
    """Check if ArgoCD is available on the Kind cluster."""
    ctx = _kubectl_context()
    try:
        result = subprocess.run(
            [
                "kubectl",
                "--context",
                ctx,
                "get",
                "pods",
                "-n",
                "argocd",
                "-l",
                "app.kubernetes.io/name=argocd-server",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return result.returncode == 0 and "Running" in result.stdout
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def _get_argocd_password() -> str | None:
    """Get ArgoCD admin password from the cluster."""
    ctx = _kubectl_context()
    try:
        result = subprocess.run(
            [
                "kubectl",
                "--context",
                ctx,
                "-n",
                "argocd",
                "get",
                "secret",
                "argocd-initial-admin-secret",
                "-o",
                "jsonpath={.data.password}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            return None
        return base64.b64decode(result.stdout).decode("utf-8")
    except (subprocess.SubprocessError, FileNotFoundError):
        return None


def _get_argocd_token(url: str, username: str, password: str) -> str | None:
    """Authenticate against ArgoCD and return a JWT API token."""
    import httpx

    try:
        with httpx.Client(verify=False, timeout=30.0) as client:
            response = client.post(
                f"{url}/api/v1/session",
                json={"username": username, "password": password},
            )
            if response.status_code == 200:
                data = response.json()
                token = data.get("token")
                return token if isinstance(token, str) else None
            print(f"ArgoCD auth failed: {response.status_code} - {response.text[:200]}")
    except Exception as e:
        print(f"ArgoCD auth error: {e}")
    return None


class PortForwardProcess:
    """Manage a kubectl port-forward subprocess for the test session."""

    def __init__(
        self,
        context: str,
        namespace: str,
        service: str,
        local_port: int,
        remote_port: int,
    ) -> None:
        self.context = context
        self.namespace = namespace
        self.service = service
        self.local_port = local_port
        self.remote_port = remote_port
        self._process: subprocess.Popen | None = None

    def start(self) -> bool:
        """Start the port-forward; return True if it is listening."""
        cmd = [
            "kubectl",
            "--context",
            self.context,
            "-n",
            self.namespace,
            "port-forward",
            f"svc/{self.service}",
            f"{self.local_port}:{self.remote_port}",
        ]

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                preexec_fn=os.setsid,
            )

            time.sleep(2)
            if self._process.poll() is not None:
                stderr = self._process.stderr.read().decode() if self._process.stderr else ""
                print(f"Port-forward failed to start: {stderr}")
                return False

            return self._verify_port_listening()
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            print(f"Failed to start port-forward: {e}")
            return False

    def _verify_port_listening(self) -> bool:
        """Confirm the chosen local port is accepting connections."""
        for _ in range(10):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                result = sock.connect_ex(("localhost", self.local_port))
                sock.close()
                if result == 0:
                    return True
            except OSError:
                pass
            time.sleep(0.5)
        return False

    def stop(self) -> None:
        """Stop the port-forward process."""
        if self._process is not None:
            try:
                os.killpg(os.getpgid(self._process.pid), signal.SIGTERM)
                self._process.wait(timeout=5)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(os.getpgid(self._process.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
            finally:
                self._process = None


@pytest.fixture(scope="session")
def argocd_port_forward() -> Iterator[int | None]:
    """Run kubectl port-forward against argocd-server for the session."""
    if not _is_argocd_available():
        yield None
        return

    local_port = 18080
    port_forward = PortForwardProcess(
        context=_kubectl_context(),
        namespace="argocd",
        service="argocd-server",
        local_port=local_port,
        remote_port=443,
    )

    if not port_forward.start():
        yield None
        return

    print(f"\nPort-forward established: localhost:{local_port} -> argocd-server:443")
    try:
        yield local_port
    finally:
        print("\nStopping port-forward...")
        port_forward.stop()


@pytest.fixture(scope="session")
def argocd_connection(argocd_port_forward: int | None) -> tuple[str, str] | None:
    """Resolve the ArgoCD (url, token) tuple, or None if unreachable."""
    if argocd_port_forward is None:
        return None

    password = _get_argocd_password()
    if password is None:
        print("Could not get ArgoCD admin password")
        return None

    url = f"https://localhost:{argocd_port_forward}"
    token = _get_argocd_token(url, "admin", password)
    if token is None:
        print("Could not get ArgoCD API token")
        return None

    print("\nArgoCD authentication successful, got API token")
    return (url, token)


@pytest.fixture(scope="session")
def argocd_instance(argocd_connection: tuple[str, str] | None) -> ArgocdInstance | None:
    """Build an ArgocdInstance for the live cluster, or None if unavailable."""
    if argocd_connection is None:
        return None

    url, token = argocd_connection
    return ArgocdInstance(
        url=url,
        token=SecretStr(token),
        name="integration-test",
        insecure=True,
    )
