from pathlib import Path
from string import Template


PROJECT = Path(__file__).parents[1]


def test_agent_voice_skill_matches_the_cli_and_delivery_contract():
    skill_root = PROJECT / "skills/agent-voice"
    skill = (skill_root / "SKILL.md").read_text(encoding="utf-8")
    fallback = (skill_root / "references/recording-delivery.md").read_text(
        encoding="utf-8"
    )

    assert "name: agent-voice" in skill
    assert 'agent-voice speak "Text to record"' in skill
    assert "printf '%s' \"$TEXT\" | agent-voice speak" in skill
    assert "speak --json" not in skill
    assert "delivery.fallback_markdown" not in skill
    assert "references/recording-delivery.md" in skill
    assert "references/recording.md" not in skill
    assert "fallback-response.md" not in skill
    assert "fallback-response-local.md" not in skill
    assert "delivery.play_command" not in skill
    assert "render the receipt's `path`" in skill
    assert "`played` value is" in skill and "`true`" in skill
    assert "/Users/" not in skill
    assert "agent-voice serve" not in skill
    assert "$browser_url" in fallback and "$audio_url" in fallback
    assert "$file_uri" in fallback and "$path" in fallback
    assert "$RECORDING_NAME" not in fallback
    assert "$PLAY_COMMAND" not in fallback


def test_spoken_responses_skill_is_explicit_and_task_scoped():
    skill_root = PROJECT / "skills/spoken-responses"
    skill = (skill_root / "SKILL.md").read_text(encoding="utf-8")
    metadata = (skill_root / "agents/openai.yaml").read_text(encoding="utf-8")

    assert "name: spoken-responses" in skill
    assert 'printf \'%s\' "$NARRATION"' in skill
    assert "$FINAL_RESPONSE" not in skill
    assert "never carries into another Thread" in skill
    assert "delivery.fallback_markdown" not in skill
    assert "references/recording-delivery.md" in skill
    assert "references/recording.md" not in skill
    assert "fallback-response.md" not in skill
    assert "fallback-response-local.md" not in skill
    assert "delivery.play_command" not in skill
    assert "render the receipt's" in skill and "`path`" in skill
    assert "--speed" not in skill and "--service" not in skill
    assert "allow_implicit_invocation: false" in metadata


def test_independently_installable_skills_own_matching_fallback_references():
    agent_voice = PROJECT / "skills/agent-voice/references"
    spoken_responses = PROJECT / "skills/spoken-responses/references"

    assert (agent_voice / "recording-delivery.md").read_text(encoding="utf-8") == (
        spoken_responses / "recording-delivery.md"
    ).read_text(encoding="utf-8")


def test_fallback_references_render_only_structured_receipt_values():
    references = PROJECT / "skills/agent-voice/references"
    common = {
        "file_uri": "file:///recordings/daily-update.mp3",
        "path": "/recordings/daily-update.mp3",
    }

    fallback = (references / "recording-delivery.md").read_text(encoding="utf-8")
    viewer = Template(fallback).substitute(
        **common,
        browser_url="http://127.0.0.1:8779/player/daily-update.html",
        audio_url="http://127.0.0.1:8779/recordings/daily-update.mp3",
    )
    local = Template(
        fallback.replace("[web player]($browser_url) · ", "").replace(
            " · [web audio]($audio_url)", ""
        )
    ).substitute(**common)

    assert "$" not in viewer
    assert "[web player](http://127.0.0.1:8779/player/daily-update.html)" in viewer
    assert "[web audio](http://127.0.0.1:8779/recordings/daily-update.mp3)" in viewer
    assert "$" not in local
    assert "[media app](file:///recordings/daily-update.mp3)" in local
    assert 'agent-voice play "/recordings/daily-update.mp3"' in local
    assert "[web player]" not in local
    assert "[web audio]" not in local


def test_readme_uses_the_published_skill_install_commands():
    readme = (PROJECT / "README.md").read_text(encoding="utf-8")

    assert (
        "npx skills add yoav0gal/agent-voice --skill agent-voice "
        "--global --agent codex --yes"
    ) in readme
    assert (
        "npx skills add yoav0gal/agent-voice --skill spoken-responses "
        "--global --agent codex --yes"
    ) in readme
    assert "skills/read-aloud" not in readme
