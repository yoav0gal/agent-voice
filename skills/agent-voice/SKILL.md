---
name: agent-voice
description: Create and deliver local speech recordings with Agent Voice. Use when the user asks to have text recorded as audio or played aloud, narrated, or read aloud.
---

# Agent Voice

Use the Agent Voice CLI to create a text-to-speech recording.

## Setup

On first use, or when readiness is missing:

```sh
uv tool install agent-voice
agent-voice setup
```

Setup prepares the speech model.

## Record

Prepare the text as you would naturally say it:

- For plain text supplied by the user, preserve every word and punctuation mark.
- For formatted text, preserve its spoken wording and order while omitting only
  presentation syntax such as Markdown markers.
- For a requested summary or explanation, write it for natural speech without
  changing its meaning.
- For tables, state the headers once and read each row as labeled values.

Always include `--json`. Treat the receipt as internal delivery data; do not
paste the full receipt into the response unless the user requests it.

```sh
agent-voice speak "Text to record" --json
```

For long text or shell-sensitive text, use:

```sh
printf '%s' "$TEXT" | agent-voice speak --json
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
agent-voice speak "Text to record" --label release-summary --json
```

Use `--output` only when the user requests an exact path or filename.

## Deliver

Use exactly one of two modes:

1. When the surface explicitly supports native audio attachments, render the
   receipt's `path` with its audio player. Do not probe with image tools or
   inline the audio as base64.
2. Otherwise return the receipt's exact `delivery.fallback_markdown`. Do not
   rewrite, combine, or omit its lines. It has this shape:

   ````markdown
   ---

   Agent Voice recording recording.mp3
   Listen: [web player](http://127.0.0.1:8779/player/recording.mp3) · [media app](file:///absolute/path/recording.mp3) · [raw audio](http://127.0.0.1:8779/recordings/recording.mp3)
   ```sh
   agent-voice play "/absolute/path/recording.mp3"
   ```

   ---
   ````

The viewer prefers localhost port `8779` and falls back to a free port if it is
occupied. The receipt always contains the current URLs. The web player renders
the branded document with its audio player and response text, the media-app link
opens the local file with the operating system default, and raw audio serves the
recording directly in a browser.

For a playback request, run `agent-voice play PATH --json` and report success
only when the receipt's `played` value is `true`. `play` runs to completion;
`Ctrl+C` stops it, and running the command again restarts from the beginning.
Do not promise pause.

## Recovery

If Agent Voice is unavailable, run the Setup commands above.

## Resources

- CLI help: `agent-voice --help`
- Source and docs: [Agent Voice on GitHub](https://github.com/yoav0gal/agent-voice)
