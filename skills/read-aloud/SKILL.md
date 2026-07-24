---
name: read-aloud
description: Use local speech synthesis when the user asks to read text aloud, speak a response, create narration, or produce an audio recording. Runs the globally installed Kokoro CLI.
---

# Read Aloud with Kokoro

Use the globally installed `kokoro` command. If it is unavailable, tell the user to run:

```sh
uv tool install kokoro-cli
kokoro setup
```

Inspect or update persistent voice and speed defaults:

```sh
kokoro config --json
kokoro config --voice bf_emma --speed 1.15
kokoro config --reset
```

Use `--voice` or `--speed` with `kokoro speak` when a change should apply only to one recording.

Create an audio recording:

```sh
kokoro speak "Text to read" --json
```

Add `--play` to play the recording aloud after creating it:

```sh
kokoro speak "Text to read" --play --json
```

Only speak text visible to the user.

Return `path`; only say it played when `played` is `true`.

Run `kokoro --help` or `kokoro <command> --help` for current commands and options.
