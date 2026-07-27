from pathlib import Path


PROJECT = Path(__file__).parents[1]


def test_agent_voice_skill_matches_the_cli_and_delivery_contract():
    skill = (PROJECT / "skills/agent-voice/SKILL.md").read_text()

    assert "name: agent-voice" in skill
    assert 'agent-voice speak "Text to record" --json' in skill
    assert "printf '%s' \"$TEXT\" | agent-voice speak --json" in skill
    assert "receipt's exact `delivery.fallback_markdown`" in skill
    assert "`played` value is" in skill and "`true`" in skill
    assert "/Users/" not in skill
    assert "agent-voice serve" not in skill
    assert "[web player](http://127.0.0.1:8779/player/recording.mp3)" in skill
    assert "[media app](file:///absolute/path/recording.mp3)" in skill
    assert "[raw audio](http://127.0.0.1:8779/recordings/recording.mp3)" in skill


def test_spoken_responses_skill_is_explicit_and_task_scoped():
    skill = (PROJECT / "skills/spoken-responses/SKILL.md").read_text()
    metadata = (PROJECT / "skills/spoken-responses/agents/openai.yaml").read_text()

    assert "name: spoken-responses" in skill
    assert 'printf \'%s\' "$NARRATION"' in skill
    assert "$FINAL_RESPONSE" not in skill
    assert "never carries into another task" in skill
    assert "delivery.fallback_markdown" in skill
    assert "--speed" not in skill and "--service" not in skill
    assert "[web player](http://127.0.0.1:8779/player/recording.mp3)" in skill
    assert "[media app](file:///absolute/path/recording.mp3)" in skill
    assert "[raw audio](http://127.0.0.1:8779/recordings/recording.mp3)" in skill
    assert "allow_implicit_invocation: false" in metadata


def test_readme_uses_the_published_skill_install_commands():
    readme = (PROJECT / "README.md").read_text()

    assert (
        "npx skills add yoav0gal/agent-voice --skill agent-voice "
        "--global --agent codex --yes"
    ) in readme
    assert (
        "npx skills add yoav0gal/agent-voice --skill spoken-responses "
        "--global --agent codex --yes"
    ) in readme
    assert "skills/read-aloud" not in readme
