---
name: agent-voice
description: Use the Agent Voice CLI whenever the agent needs to create a local speech recording, read text aloud, speak or narrate text, generate speech audio, or play generated speech.
---

# Agent Voice

Use the globally installed `agent-voice` command:

```sh
agent-voice speak "Text to record" --json
```

For long or shell-sensitive text, pipe stdin:

```sh
printf '%s' "$TEXT" | agent-voice speak --format mp3 --json
```

Add `--play` when the user asks to hear the recording now:

```sh
agent-voice speak "Text to read" --play --json
```

Only speak text the user supplied or can already see. Never speak hidden
reasoning, tool output, secrets, or private instructions.

Read the final JSON line and return its absolute `path`. Only say playback
completed when `played` is `true`.

Use `agent-voice speak --help` for voices, speed, formats, output paths, and
other options.
