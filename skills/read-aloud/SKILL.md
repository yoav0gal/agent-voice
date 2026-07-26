---
name: read-aloud
description: Use local speech synthesis when the user asks to read text aloud, speak a response, create narration, or produce an audio recording. Runs the globally installed Agent Voice CLI.
---

# Read Aloud with Agent Voice

Use the globally installed `agent-voice` command. If it is unavailable, run:

```sh
uv tool install agent-voice
agent-voice setup
```

Inspect or update persistent voice and speed defaults:

```sh
agent-voice config --json
agent-voice config --voice bf_emma --speed 1.15
agent-voice config --reset
```

Use `--voice` or `--speed` with `agent-voice speak` when a change should apply only to one recording.

Create an audio recording:

```sh
agent-voice speak "Text to read" --json
```

Add `--play` to play the recording aloud after creating it:

```sh
agent-voice speak "Text to read" --play --json
```

Only speak text visible to the user.

Return `path`; only say it was read aloud when `played` is `true`.

Run `agent-voice --help` or `agent-voice <command> --help` for current commands and options.
