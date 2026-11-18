"""A small client for the Langfuse public API, used by setup to prove keys and confirm traces."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from kit.errors import connection_error

# Langfuse Cloud regions, in the order setup tries a key pair against them.
CLOUD_HOSTS = (
    ("US", "https://us.cloud.langfuse.com"),
    ("EU", "https://cloud.langfuse.com"),
    ("Japan", "https://jp.cloud.langfuse.com"),
    ("HIPAA", "https://hipaa.cloud.langfuse.com"),
)

# Seconds to wait on a 429 that does not say how long to wait.
DEFAULT_RETRY_AFTER = 1.0


def region_name(host: str) -> str | None:
    host = host.rstrip("/")
    return next((name for name, url in CLOUD_HOSTS if url == host), None)


class KeysRejected(Exception):
    """The host answered, and it does not accept this key pair."""


@dataclass(frozen=True)
class Project:
    id: str
    name: str


class LangfuseApi:
    """Basic auth with a project key pair: public key as user, secret key as password."""

    def __init__(
        self,
        host: str,
        public_key: str,
        secret_key: str,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        timeout: float = 20.0,
    ) -> None:
        self.host = host.rstrip("/")
        self._sleep = sleep
        self._http = httpx.Client(
            base_url=self.host,
            auth=(public_key, secret_key),
            transport=transport,
            timeout=timeout,
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """One request. A 429 waits for `Retry-After` and tries once more. Rejected keys raise."""
        response = self._send(method, path, params, json, headers)
        if response.status_code == 429:
            self._sleep(_retry_after(response))
            response = self._send(method, path, params, json, headers)
        if response.status_code in (401, 403):
            raise KeysRejected(f"{self.host} answered {response.status_code}")
        return response

    def get(self, path: str, **params: Any) -> httpx.Response:
        """One GET that must succeed."""
        response = self.request("GET", path, params=params)
        response.raise_for_status()
        return response

    def post(self, path: str, json: Any = None, headers: dict[str, str] | None = None) -> httpx.Response:
        """One POST. The caller reads the status, so partial and server failures can be handled.

        A timeout is raised as is, because the caller cannot know whether the write landed.
        """
        return self.request("POST", path, json=json, headers=headers)

    def _send(self, method, path, params, json, headers) -> httpx.Response:
        try:
            return self._http.request(method, path, params=params, json=json, headers=headers)
        except httpx.TimeoutException as exc:
            if method == "POST":
                raise
            raise connection_error(exc) from exc
        except httpx.TransportError as exc:
            raise connection_error(exc) from exc

    def project(self) -> Project:
        """The project this key pair belongs to."""
        data = self.get("/api/public/projects").json().get("data") or []
        if not data:
            raise KeysRejected(f"{self.host} returned no project for this key pair")
        return Project(id=str(data[0]["id"]), name=str(data[0].get("name", "")))

    def trace_has_observations(self, trace_id: str) -> bool:
        """One read by trace ID through the v2 observations endpoint."""
        data = self.get("/api/public/v2/observations", traceId=trace_id).json().get("data") or []
        return bool(data)


def _retry_after(response: httpx.Response) -> float:
    try:
        return max(0.0, float(response.headers.get("Retry-After", DEFAULT_RETRY_AFTER)))
    except ValueError:
        return DEFAULT_RETRY_AFTER
