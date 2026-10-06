import pytest


@pytest.fixture(autouse=True)
def isolated_agent_home(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_VOICE_HOME", str(tmp_path / "agent-home"))
