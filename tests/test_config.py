from pathlib import Path

from kit import config
from kit.console import mask


def test_values_round_trip_through_env_file(kit_home):
    values = {
        config.LANGFUSE_PUBLIC_KEY: "pk-lf-1234",
        config.LANGFUSE_SECRET_KEY: "sk-lf-5678",
        config.LLM_KEY: "sk-or-v1-abcd",
    }
    config.write_env(values)
    assert config.read_env() == values


def test_env_file_with_byte_order_mark_reads_cleanly(kit_home):
    (kit_home / ".env").write_bytes("﻿LANGFUSE_PUBLIC_KEY=pk-lf-1\r\n".encode("utf-8"))
    assert config.read_env() == {"LANGFUSE_PUBLIC_KEY": "pk-lf-1"}


def test_pasted_quotes_and_whitespace_are_stored_clean(kit_home):
    config.write_env({config.LLM_KEY: '  "sk-or-xyz"  \n'})
    assert (kit_home / ".env").read_text() == "WORKSHOP_LLM_KEY=sk-or-xyz\n"
    assert config.read_env()[config.LLM_KEY] == "sk-or-xyz"


def test_mask_shows_only_prefix_and_last_four():
    assert mask("sk-lf-0123456789abcdef") == "sk-lf-...cdef"
    assert mask("sk-or-v1-secretsecret9876") == "sk-or-v1-...9876"
    assert mask("pk-lf-12") == "pk-lf-..."
    assert mask("") == "(empty)"


def test_example_file_values_are_placeholders_and_real_keys_are_not():
    example = config.read_env(Path(__file__).parent.parent / ".env.example")
    assert example  # the example file still lists the five keys
    assert all(config.is_placeholder(value) for value in example.values())
    for real in ("pk-lf-1234", "sk-lf-0123456789abcdef", "sk-or-v1-abcd", ""):
        assert not config.is_placeholder(real)
