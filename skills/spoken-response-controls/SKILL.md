---
name: spoken-response-controls
description: Create the spoken semantic twin of an assistant response with clickable Agent Voice playback controls. Use when the user explicitly requests controlled playback on a compatible desktop renderer.
---

# Spoken Response Controls

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
2. Set `RESPONSE_AS_MARKDOWN` to the selected response's Markdown. Use real line
   breaks, not escaped `\n` text.
3. Set `RESPONSE_AS_TEXT` to its spoken semantic twin: preserve meaning, detail,
   and order while translating formatting into natural speech. Never use
   `RESPONSE_AS_MARKDOWN` as the speech input.
   - For tables, state the headers once and read each row as labeled values.
   - For long code, explain it naturally and refer to the written response for
     exact syntax.
4. Set `LABEL` to `SR`. When a thread title is already available, use
   `<title> - SR`.
5. Create the recording with the configured voice, speed, and format:

   ```sh
   agent-voice speak "$RESPONSE_AS_TEXT" --markdown "$RESPONSE_AS_MARKDOWN" --label "$LABEL" --controls
   ```

   For long responses, use temporary files outside the workspace and remove them
   afterward:

   ```sh
   agent-voice speak --label "$LABEL" --response-file "$RESPONSE_AS_MARKDOWN_FILE" --controls < "$RESPONSE_AS_TEXT_FILE"
   ```

6. Place the controls above the written response or `Previous` confirmation using
   [default.md](references/delivery/default.md).

For speaker playback, add `--play` and complete after the result reports
`played: true`. On synthesis failure, send the written response with a brief
failure note.

## Setup

If `agent-voice` is unavailable:

```sh
uv tool install agent-voice
agent-voice setup
agent-voice controls install
```

## Resources

- CLI help: `agent-voice --help`
- Source and docs: [Agent Voice on GitHub](https://github.com/yoav0gal/agent-voice)
