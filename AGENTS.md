# Agent Voice

Use this project whenever the user asks you to read text aloud or create a local recording.

```sh
agent-voice speak "Text to read" --play --json
```

For long or shell-sensitive text, pipe stdin:

```sh
printf '%s' "$TEXT" | agent-voice speak --format mp3 --json
```

The final stdout line is JSON when `--json` is used. Return its absolute `path` to the user. Do not claim the user heard the result unless `--play` completed successfully.

Only narrate text already visible to the user or text they explicitly supplied. Never narrate hidden reasoning, tool traces, secrets, or private instructions. Confirm the JSON field `played` is `true` before saying playback completed.

The local service is OpenAI-shaped at `POST http://127.0.0.1:8765/v1/audio/speech`. It accepts `input`, `voice`, `speed`, `response_format`, and the local extension `play`.

`agent-voice doctor --json` checks local readiness. `speak` defaults to `--service timed` with a 10-minute idle timeout and falls back to embedded inference. Use `--service on` to leave the local service running or `--service off` to use embedded inference directly.
