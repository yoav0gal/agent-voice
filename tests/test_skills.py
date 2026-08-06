from pathlib import Path
from string import Template


PROJECT = Path(__file__).parents[1]


def test_create_speech_recording_skill_matches_cli_and_delivery_contract():
    skill_root = PROJECT / "skills/create-speech-recording"
    skill = (skill_root / "SKILL.md").read_text(encoding="utf-8")
    fallback = (skill_root / "references/delivery/default.md").read_text(
        encoding="utf-8"
    )

    assert "name: create-speech-recording" in skill
    assert (
        'agent-voice speak "$RESPONSE_AS_TEXT" '
        '--markdown "$RESPONSE_AS_MARKDOWN"' in skill
    )
    assert (
        '--response-file "$RESPONSE_AS_MARKDOWN_FILE" '
        '< "$RESPONSE_AS_TEXT_FILE"' in skill
    )
    assert "temporary files outside the workspace" in " ".join(skill.split())
    assert "remove them afterward" in " ".join(skill.split())
    assert "Never use `RESPONSE_AS_MARKDOWN` as the speech input." in " ".join(
        skill.split()
    )
    assert 'agent-voice speak "$TEXT" --markdown "$RESPONSE"' not in skill
    assert "speak --json" not in skill
    assert "delivery.fallback_markdown" not in skill
    assert "references/delivery/default.md" in skill
    assert "Desktop" not in skill
    assert "`default`:" not in skill
    assert "references/recording.md" not in skill
    assert "fallback-response.md" not in skill
    assert "fallback-response-local.md" not in skill
    assert "delivery.play_command" not in skill
    assert "render the returned `path`" in fallback
    assert "`played: true`" in skill
    assert "/Users/" not in skill
    assert "agent-voice serve" not in skill
    assert "$browser_url" in fallback and "$audio_url" in fallback
    assert "$file_uri" in fallback and "$path" in fallback
    assert "$RECORDING_NAME" not in fallback
    assert "$PLAY_COMMAND" not in fallback


def test_readme_distinguishes_spoken_text_from_written_markdown():
    readme = (PROJECT / "README.md").read_text(encoding="utf-8")
    assert 'agent-voice speak "$RESPONSE_AS_TEXT"' in readme
    assert '--markdown "$RESPONSE_AS_MARKDOWN"' in readme
    assert '--response-file "$RESPONSE_AS_MARKDOWN_FILE"' in readme
    assert '< "$RESPONSE_AS_TEXT_FILE"' in readme
    assert 'agent-voice speak "$TEXT" --markdown "$RESPONSE"' not in readme
    assert "--skill create-speech-recording-desktop --global" in readme
    assert "--skill spoken-response-desktop --global" in readme
    assert "Desktop skills are explicitly invoked in Codex" in " ".join(readme.split())


def test_spoken_response_skill_matches_thread_modes_and_delivery_contract():
    skill_root = PROJECT / "skills/spoken-response"
    skill = (skill_root / "SKILL.md").read_text(encoding="utf-8")
    metadata = (skill_root / "agents/openai.yaml").read_text(encoding="utf-8")

    assert "name: spoken-response" in skill
    assert "spoken semantic twin" in skill
    assert (
        'agent-voice speak "$RESPONSE_AS_TEXT" '
        '--markdown "$RESPONSE_AS_MARKDOWN"' in skill
    )
    assert (
        '--response-file "$RESPONSE_AS_MARKDOWN_FILE" '
        '< "$RESPONSE_AS_TEXT_FILE"' in skill
    )
    assert "temporary files outside the workspace" in " ".join(skill.split())
    assert "remove them afterward" in " ".join(skill.split())
    assert "Never use `RESPONSE_AS_MARKDOWN` as the speech input." in " ".join(
        skill.split()
    )
    assert 'agent-voice speak "$TEXT" --markdown "$RESPONSE"' not in skill
    assert "`Thread`" in skill
    assert "delivery.fallback_markdown" not in skill
    assert "references/delivery/default.md" in skill
    assert "Desktop" not in skill
    assert "`default`:" not in skill
    assert "references/recording.md" not in skill
    assert "fallback-response.md" not in skill
    assert "fallback-response-local.md" not in skill
    assert "delivery.play_command" not in skill
    assert "--speed" not in skill and "--service" not in skill
    assert "allow_implicit_invocation: true" in metadata


def test_portable_and_desktop_skills_are_independently_installable():
    agent_voice = PROJECT / "skills/create-speech-recording/references"
    spoken_responses = PROJECT / "skills/spoken-response/references"

    assert (agent_voice / "delivery/default.md").read_text(encoding="utf-8") == (
        spoken_responses / "delivery/default.md"
    ).read_text(encoding="utf-8")

    agent_voice = PROJECT / "skills/create-speech-recording-desktop"
    spoken_responses = PROJECT / "skills/spoken-response-desktop"
    for root, name in (
        (agent_voice, "create-speech-recording-desktop"),
        (spoken_responses, "spoken-response-desktop"),
    ):
        skill = (root / "SKILL.md").read_text(encoding="utf-8")
        metadata = (root / "agents/openai.yaml").read_text(encoding="utf-8")
        assert f"name: {name}" in skill
        assert "allow_implicit_invocation: false" in metadata
        assert "references/delivery/codex-desktop.md" in skill
        assert "references/delivery/opencode-desktop.md" in skill
        assert not (root / "references/delivery/default.md").exists()

    for name in ("codex-desktop.md", "opencode-desktop.md"):
        assert (agent_voice / "references/delivery" / name).read_text(
            encoding="utf-8"
        ) == (spoken_responses / "references/delivery" / name).read_text(
            encoding="utf-8"
        )


def test_desktop_skills_only_change_identity_and_delivery():
    pairs = (
        ("create-speech-recording", "create-speech-recording-desktop"),
        ("spoken-response", "spoken-response-desktop"),
    )

    def shared_workflow(name):
        skill = (PROJECT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
        body = skill.split("---\n", 2)[2]
        body = body.replace(" Desktop\n", "\n", 1)
        if "## Deliver\n" in body:
            before, _, remainder = body.partition("## Deliver\n")
            _, _, after = remainder.partition("## Setup\n")
            return before + "## Setup\n" + after
        before, _, remainder = body.partition("6. Place")
        _, _, after = remainder.partition("\n\nFor speaker playback")
        return before + "For speaker playback" + after

    for portable, desktop in pairs:
        assert shared_workflow(portable) == shared_workflow(desktop)


def test_codex_desktop_reference_owns_player_and_visualize_contract():
    reference = (
        PROJECT
        / "skills/create-speech-recording-desktop/references/delivery/codex-desktop.md"
    ).read_text(encoding="utf-8")
    rendered = Template(reference).substitute(
        PLAYER_ID="agent-voice-daily-update",
        RECORDING_NAME="daily-update.mp3",
        MIME="audio/mpeg",
        BASE64="QUJD",
        audio_url="data:audio/mpeg;base64,QUJD",
        ABSOLUTE_HTML_PATH="/visualizations/daily-update.html",
    )

    assert reference.startswith("# Codex Desktop")
    assert "data:$MIME;base64,$BASE64" in reference
    assert "outside the repository" in " ".join(reference.split())
    assert "1 MB" not in reference
    assert '<audio controls preload="metadata"' in reference
    assert 'visualize{"path":"$ABSOLUTE_HTML_PATH"' in reference
    assert "$" not in rendered


def test_specialized_delivery_references_share_the_player_template():
    references = PROJECT / "skills/create-speech-recording-desktop/references/delivery"
    codex = (references / "codex-desktop.md").read_text(encoding="utf-8")
    opencode = (references / "opencode-desktop.md").read_text(encoding="utf-8")

    codex_html = codex.split("```html\n", 1)[1].split("\n```", 1)[0]
    opencode_html = opencode.split("```html\n", 1)[1].split("\n```", 1)[0]

    assert codex_html == opencode_html


def test_opencode_desktop_reference_renders_inline_localhost_player():
    reference = (
        PROJECT
        / "skills/create-speech-recording-desktop/references/delivery/opencode-desktop.md"
    ).read_text(encoding="utf-8")
    rendered = Template(reference).substitute(
        PLAYER_ID="agent-voice-daily-update",
        RECORDING_NAME="daily-update.mp3",
        audio_url="http://127.0.0.1:8779/recordings/daily-update.mp3",
    )

    assert "$" not in rendered
    assert reference.startswith("# OpenCode Desktop")
    assert "delivery.audio_url" in reference
    assert "without the code fence" in " ".join(reference.split())
    assert "<style" not in rendered
    assert "daily-update.mp3" in rendered
    assert '<audio controls preload="metadata"' in rendered
    assert '<svg xmlns="http://www.w3.org/2000/svg" width="42" height="42"' in rendered
    assert rendered.index("<audio ") < rendered.index("<svg ")
    assert "margin:0 0 .375rem" in rendered
    assert "margin:0 0 1.125rem" in rendered
    assert "raw.githubusercontent.com" not in rendered
    assert "http://127.0.0.1:8779/assets/" not in rendered
    assert "data:image/svg+xml;base64," not in rendered
    assert "filter:invert(49%) sepia(98%)" in rendered
    assert '<g fill="#000000">' in rendered
    assert "url(#agent-voice-gradient)" not in rendered


def test_fallback_references_render_only_structured_receipt_values():
    references = PROJECT / "skills/create-speech-recording/references"
    common = {
        "file_uri": "file:///recordings/daily-update.mp3",
        "path": "/recordings/daily-update.mp3",
    }

    fallback = (references / "delivery/default.md").read_text(encoding="utf-8")
    template = fallback.split("````markdown\n", 1)[1].rsplit("\n````", 1)[0]
    viewer = Template(template).substitute(
        **common,
        browser_url="http://127.0.0.1:8779/player/daily-update.html",
        audio_url="http://127.0.0.1:8779/recordings/daily-update.mp3",
    )
    local = Template(
        template.replace("[web player]($browser_url) · ", "").replace(
            " · [web audio]($audio_url)", ""
        )
    ).substitute(**common)

    assert not fallback.startswith("#")
    assert "Send the result without the outer code fence" in fallback
    assert template.startswith("---\n") and template.endswith("\n---")
    assert "$" not in viewer
    assert "[web player](http://127.0.0.1:8779/player/daily-update.html)" in viewer
    assert "[web audio](http://127.0.0.1:8779/recordings/daily-update.mp3)" in viewer
    assert "$" not in local
    assert "[media app](file:///recordings/daily-update.mp3)" in local
    assert 'agent-voice play "/recordings/daily-update.mp3"' in local
    assert "[web player]" not in local
    assert "[web audio]" not in local
