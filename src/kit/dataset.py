"""The golden dataset: the ten tickets with their expected answers.

It also marks a project as holding workshop history: its metadata carries the run ID
and anchor time of the history load.
"""

from __future__ import annotations

from typing import Any

from kit import tickets

NAME = "workshop-golden"
DESCRIPTION = "Customer tickets with the answers the customer expected."


def marker(api: Any) -> dict[str, Any] | None:
    """The history metadata stored on the dataset, or None when the dataset does not exist."""
    response = api.request("GET", f"/api/public/v2/datasets/{NAME}")
    if response.status_code == 404:
        return None
    response.raise_for_status()
    metadata = response.json().get("metadata") or {}
    return metadata if metadata.get("run_id") else {}


def ensure_marker(api: Any, run_id: str, anchor_ns: int) -> None:
    existing = marker(api)
    if existing and existing.get("run_id") == run_id:
        return
    response = api.post(
        "/api/public/v2/datasets",
        json={"name": NAME, "description": DESCRIPTION, "metadata": {"run_id": run_id, "anchor_ns": str(anchor_ns)}},
    )
    response.raise_for_status()


def item_id(ticket_id: str) -> str:
    return f"ticket-{ticket_id}"


def add_ticket_items(api: Any) -> None:
    """Create or update one item per ticket. The same IDs are sent every time."""
    for ticket in tickets.load():
        response = api.post(
            "/api/public/dataset-items",
            json={
                "datasetName": NAME,
                "id": item_id(ticket.id),
                "input": ticket.question,
                "expectedOutput": ticket.expected,
                "metadata": {"customer": ticket.customer, "ticket": ticket.id},
            },
        )
        response.raise_for_status()
