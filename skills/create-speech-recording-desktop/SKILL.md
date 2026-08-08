---
name: create-speech-recording-desktop
description: Create and embed a speech recording in Codex Desktop, Antigravity App, or OpenCode Desktop.
---

# Create Speech Recording Desktop

Agent Voice works best in English. For another supported language, choose a
matching voice with `agent-voice voices` and pass `--voice` and `--lang`.

## Prepare

Set `RESPONSE_AS_MARKDOWN` to the original text or Markdown. Set
`RESPONSE_AS_TEXT` to its spoken form. Never use `RESPONSE_AS_MARKDOWN` as the
speech input.
Use real line breaks in `RESPONSE_AS_MARKDOWN`, not escaped `\n` text.

- For supplied text, preserve every word and punctuation mark in order while
  translating presentation syntax into speech.
- For a requested summary or explanation, write natural speech with the same
  meaning.
- For tables, state the headers once and read each row as labeled values.

## Record

```sh
agent-voice speak "$RESPONSE_AS_TEXT" --markdown "$RESPONSE_AS_MARKDOWN"
```

For long text, use temporary files outside the workspace and remove them afterward:

```sh
agent-voice speak --label "$LABEL" --response-file "$RESPONSE_AS_MARKDOWN_FILE" < "$RESPONSE_AS_TEXT_FILE"
```

On Antigravity App, follow the special
[recording and delivery instructions](references/delivery/antigravity.md).

Set `LABEL` to a short subject. For an exact requested filename, replace
`--label "$LABEL"` with `--output "$PATH"`.

Use the returned `path` to deliver the recording. For speaker playback, add
`--play` and complete after the result reports `played: true`.

## Deliver

Use the first matching delivery reference:

- Antigravity App: [antigravity.md](references/delivery/antigravity.md)
- OpenCode Desktop: [opencode-desktop.md](references/delivery/opencode-desktop.md)
- Other (Codex Desktop): [default.md](references/delivery/default.md)

## Setup

If the command is unavailable:

```sh
uv tool install agent-voice
agent-voice setup
```

## Resources

- CLI help: `agent-voice --help`
- Source and docs: [Agent Voice on GitHub](https://github.com/yoav0gal/agent-voice)
