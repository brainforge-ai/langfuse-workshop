"""The ten customer tickets attendees send through the agent."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files


@dataclass(frozen=True)
class Ticket:
    id: str
    customer: str
    complaint: str
    question: str
    expected: str


def load() -> list[Ticket]:
    raw = json.loads((files("kit") / "data" / "tickets.json").read_text(encoding="utf-8"))
    return [Ticket(**item) for item in raw]


def get(number: int) -> Ticket | None:
    tickets = load()
    if 1 <= number <= len(tickets):
        return tickets[number - 1]
    return None
