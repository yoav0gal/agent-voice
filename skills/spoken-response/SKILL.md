---
name: spoken-response
description: Create the spoken semantic twin of an assistant response with Agent Voice. Use when the user requests a spoken response, the previous response as audio, or spoken responses for a thread.
---

# Spoken Response

A spoken response is the audio semantic twin of an assistant response.

## Mode

Choose the mode from the user's request:

- `Single` — create audio for the current response. This is the default.
- `Previous` — create audio for the most recent assistant response and return a
  brief confirmation.
- `Thread` — create audio for the current and later responses until disabled or
  the thread ends.

## Respond

1. Select the response:
   - For `Single` and `Thread`, finalize the current response.
   - For `Previous`, use the most recent assistant response.
2. Set `TEXT` to the selected response's semantic twin: preserve meaning,
   detail, and order while translating formatting into natural speech.
   - For tables, state the headers once and read each row as labeled values.
   - For long code, explain it naturally and refer to the written response for
     exact syntax.
3. Set `LABEL` to `SR`. When a thread title is already available, use
   `<title> - SR`.
4. Create the recording with the configured voice, speed, and format. For a
   short response:

   ```sh
   printf '%s' "$TEXT" |
     agent-voice speak --label "$LABEL"
   ```

   For a long response, use a file:

   ```sh
   agent-voice speak --label "$LABEL" < "$TEXT_FILE"
   ```

5. Place the audio above the written response or `Previous` confirmation using
   one delivery mode:
   - If the current surface supports an audio player, render the returned
     `path`.
   - Otherwise, render
     [recording-delivery.md](references/recording-delivery.md) with `path`,
     `file_uri`, and the available `delivery.browser_url` and
     `delivery.audio_url` values.

For speaker playback, add `--play` and complete after the result reports
`played: true`. On synthesis failure, send the written response with a brief
failure note.

## Setup

If `agent-voice` is unavailable:

```sh
uv tool install agent-voice
agent-voice setup
```

## Resources

- CLI help: `agent-voice --help`
- Source and docs: [Agent Voice on GitHub](https://github.com/yoav0gal/agent-voice)
