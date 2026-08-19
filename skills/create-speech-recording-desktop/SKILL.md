---
name: create-speech-recording-desktop
description: Create and embed a speech recording in Codex Desktop, Antigravity App, or OpenCode Desktop.
---

# Create Speech Recording Desktop

Agent Voice works best in English. For another supported language, choose a
matching voice with `agent-voice voices` and pass `--voice` and `--lang`.

## Prepare

Set `RESPONSE_AS_TEXT` to the text's spoken form.

- For supplied text, preserve every word and punctuation mark in order while
  translating presentation syntax into speech.
- For a requested summary or explanation, write natural speech with the same
  meaning.
- For tables, state the headers once and read each row as labeled values.

## Record

```sh
agent-voice speak "$RESPONSE_AS_TEXT" --wait
```

For long text, create a unique file in the system temporary directory. The
operating system handles cleanup.

```sh
agent-voice speak --label "$LABEL" --wait < "$RESPONSE_AS_TEXT_FILE"
```

On OpenCode Desktop, omit `--wait`. On Antigravity App, follow the special
[recording and delivery instructions](references/delivery/antigravity.md).

Set `LABEL` to a short subject. For an exact requested filename, replace
`--label "$LABEL"` with `--output "$PATH"`.

Use the matching delivery reference. For speaker playback, add `-p`; continue
after the result reports `playback.state: "started"`. Add
`--play-after SECONDS` to schedule it without blocking.

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
