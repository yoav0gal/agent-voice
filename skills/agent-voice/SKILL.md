---
name: agent-voice
description: Create and deliver local speech recordings with Agent Voice. Use when the user asks to have text recorded as audio or played aloud, narrated, or read aloud.
---

# Agent Voice

Use the Agent Voice CLI to create a text-to-speech recording.

Agent Voice accepts English text only.

## Record

Prepare the text as you would naturally say it:

- When reading supplied text aloud, preserve every word and punctuation mark.
  - When audio accompanies a written response as a listening medium for it (not summary or extra explanation), record the exact visible wording.
- For formatted text, preserve its spoken wording and order while omitting only
  presentation syntax such as Markdown markers.
- For a requested summary or explanation, write it for natural speech without
  changing its meaning.
- For tables, state the headers once and read each row as labeled values.

Every `speak` command returns a JSON receipt. Treat it as internal delivery
data; do not paste the full receipt into the response unless the user requests
it.

```sh
agent-voice speak "Text to record"
```

For long text or shell-sensitive text, use:

```sh
printf '%s' "$TEXT" | agent-voice speak
```

See `agent-voice speak --help` for one-time overrides, or
`agent-voice config --help` to change the defaults.

Add `--play` when immediate local playback is requested.
Report that playback completed only when the JSON receipt's `played` value is
`true`.

## Naming

Choose a short, relevant name when the recording has a clear subject or title.
Use `--label` and let Agent Voice manage the final filename:

```sh
agent-voice speak "Text to record" --label release-summary
```

Use `--output` only when the user requests an exact path or filename.

## Deliver

Use one delivery mode:

1. If the current surface supports an audio player, render the receipt's `path`.
2. Otherwise render
   [recording-delivery.md](references/recording-delivery.md) before the written
   response using values from the `agent-voice speak` response:
   - `$path`: `path`
   - `$file_uri`: `file_uri`
   - `$browser_url`: `delivery.browser_url`
   - `$audio_url`: `delivery.audio_url`
   - If the viewer fields are absent, remove their links and separators.

For a playback request, run `agent-voice play PATH --json`.

## Recovery

If Agent Voice is unavailable, run the Setup commands:

```sh
uv tool install agent-voice
agent-voice setup
```

## Resources

- CLI help: `agent-voice --help`
- Source and docs: [Agent Voice on GitHub](https://github.com/yoav0gal/agent-voice)
