"""An in-process stand-in for the Langfuse public API, served through httpx.MockTransport."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable

import httpx


class FakeLangfuse:
    def __init__(self, project_id: str = "proj1", project_name: str = "langfuse-workshop") -> None:
        self.project = {"id": project_id, "name": project_name}
        self.requests: list[httpx.Request] = []
        self.datasets: dict[str, dict] = {}
        self.dataset_items: dict[str, dict] = {}
        self.otlp_bodies: list[dict] = []
        self.scores: dict[str, dict] = {}
        self.evaluators: list[dict] = []
        self.rules: list[dict] = []
        self.llm_connections: list[dict] = []
        # Path -> list of callables; each answers one matching request, then is used up.
        self.overrides: dict[str, list[Callable[[httpx.Request], httpx.Response]]] = defaultdict(list)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def calls(self, method: str, path: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.method == method and r.url.path == path]

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        queue = self.overrides.get(f"{request.method} {path}")
        if queue:
            return queue.pop(0)(request)
        body = json.loads(request.content) if request.content else None
        route = (request.method, path)

        if route == ("GET", "/api/public/projects"):
            return httpx.Response(200, json={"data": [self.project]})
        if request.method == "GET" and path.startswith("/api/public/v2/datasets/"):
            name = path.rsplit("/", 1)[-1]
            if name not in self.datasets:
                return httpx.Response(404, json={"message": "Dataset not found"})
            return httpx.Response(200, json=self.datasets[name])
        if route == ("POST", "/api/public/v2/datasets"):
            self.datasets[body["name"]] = {"id": f"ds-{body['name']}", **body}
            return httpx.Response(200, json=self.datasets[body["name"]])
        if route == ("POST", "/api/public/dataset-items"):
            self.dataset_items[body["id"]] = body
            return httpx.Response(200, json=body)
        if route == ("POST", "/api/public/otel/v1/traces"):
            self.otlp_bodies.append(body)
            return httpx.Response(200, json={})
        if route == ("POST", "/api/public/scores"):
            for score in body:
                self.scores[score["id"]] = score
            return httpx.Response(202, json={})
        if route == ("GET", "/api/public/v2/observations"):
            return httpx.Response(200, json={"data": []})
        if route == ("GET", "/api/public/llm-connections"):
            return httpx.Response(200, json={"data": self.llm_connections, "meta": {"cursor": None}})
        if route == ("GET", "/api/public/v2/evaluators"):
            return httpx.Response(200, json={"data": self.evaluators, "meta": {"cursor": None}})
        if route == ("POST", "/api/public/v2/evaluators"):
            created = {"id": f"ev-{len(self.evaluators) + 1}", **body}
            self.evaluators.append(created)
            return httpx.Response(200, json=created)
        if route == ("GET", "/api/public/v2/evaluation-rules"):
            return httpx.Response(200, json={"data": self.rules, "meta": {"cursor": None}})
        if route == ("POST", "/api/public/v2/evaluation-rules"):
            created = {"id": f"rule-{len(self.rules) + 1}", **body}
            self.rules.append(created)
            return httpx.Response(200, json=created)
        return httpx.Response(404, json={"message": f"no fake route for {request.method} {path}"})

    def otlp_spans(self) -> list[dict]:
        return [
            span
            for body in self.otlp_bodies
            for rs in body["resourceSpans"]
            for ss in rs["scopeSpans"]
            for span in ss["spans"]
        ]


def respond(status: int, json_body: dict | None = None, headers: dict | None = None):
    return lambda request: httpx.Response(status, json=json_body or {}, headers=headers or {})


def timeout(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("timed out", request=request)
