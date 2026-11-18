"""Known failures the kit explains to the attendee as a code plus a fix line."""

from __future__ import annotations

# Every code the kit can print. The README troubleshooting table lists each one.
LF_KEY_SWAPPED = "LF-KEY-SWAPPED"
LF_NOT_A_LANGFUSE_KEY = "LF-NOT-A-LANGFUSE-KEY"
LF_KEYPAIR = "LF-KEYPAIR"
LF_PROJECT_MISMATCH = "LF-PROJECT-MISMATCH"
LF_TRACE_UNCONFIRMED = "LF-TRACE-UNCONFIRMED"
LLM_NOT_AN_LLM_KEY = "LLM-NOT-AN-LLM-KEY"
LLM_KEY = "LLM-KEY"
LLM_RATE = "LLM-RATE"
LLM_MODEL = "LLM-MODEL"
NET_TLS = "NET-TLS"
NET_OFFLINE = "NET-OFFLINE"
HIST_ALREADY_LOADED = "HIST-ALREADY-LOADED"
EVAL_NO_CONNECTION = "EVAL-NO-CONNECTION"
EVAL_NAME_TAKEN = "EVAL-NAME-TAKEN"
KIT_NOT_SET_UP = "KIT-NOT-SET-UP"
KIT_UNEXPECTED = "KIT-UNEXPECTED"

ALL_CODES = (
    LF_KEY_SWAPPED,
    LF_NOT_A_LANGFUSE_KEY,
    LF_KEYPAIR,
    LF_PROJECT_MISMATCH,
    LF_TRACE_UNCONFIRMED,
    LLM_NOT_AN_LLM_KEY,
    LLM_KEY,
    LLM_RATE,
    LLM_MODEL,
    NET_TLS,
    NET_OFFLINE,
    HIST_ALREADY_LOADED,
    EVAL_NO_CONNECTION,
    EVAL_NAME_TAKEN,
    KIT_NOT_SET_UP,
    KIT_UNEXPECTED,
)


class KitError(Exception):
    """A failure with a known cause. The CLI prints it without a traceback."""

    def __init__(self, code: str, message: str, fix: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.fix = fix


def not_set_up() -> KitError:
    return KitError(
        KIT_NOT_SET_UP,
        "The kit has no saved credentials yet.",
        "Run `uv run kit setup` first.",
    )
