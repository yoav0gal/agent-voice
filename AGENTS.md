# Kokoro CLI

Use this project whenever the user asks you to read text aloud or create a local recording.

```sh
kokoro speak "Text to read" --play --json
```

For long or shell-sensitive text, pipe stdin:

```sh
printf '%s' "$TEXT" | kokoro speak --format mp3 --json
```

The final stdout line is JSON when `--json` is used. Return its absolute `path` to the user. Do not claim the user heard the result unless `--play` completed successfully.

Only narrate text already visible to the user or text they explicitly supplied. Never narrate hidden reasoning, tool traces, secrets, or private instructions. Confirm the JSON field `played` is `true` before saying playback completed.

The local service is OpenAI-shaped at `POST http://127.0.0.1:8765/v1/audio/speech`. It accepts `input`, `voice`, `speed`, `response_format`, and the local extension `play`.

`kokoro doctor --json` checks local readiness. `speak` uses the healthy localhost service in `--service auto` mode and falls back to embedded inference; use `--service required` or `--service off` for strict behavior.
