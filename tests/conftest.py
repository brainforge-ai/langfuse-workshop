import pytest


@pytest.fixture
def kit_home(tmp_path, monkeypatch):
    """Point the kit's `.env` and `.kit/` at an empty temporary folder."""
    monkeypatch.setenv("KIT_HOME", str(tmp_path))
    return tmp_path
