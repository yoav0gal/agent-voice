---
name: create-speech-recording-controls
description: Turn text into speech with Agent Voice and clickable playback controls. Use when the user explicitly requests controlled playback on a compatible desktop renderer.
---

# Create Speech Recording Controls

Agent Voice works best in English. For another supported language, choose a
matching voice with `agent-voice voices` and pass `--voice` and `--lang`.

## Prepare

Set `RESPONSE_AS_TEXT` to the text's spoken form.

- Use speech-ready plain text, not serialized text. Convert literal `\n`, `\r`,
  `\t`, `&#x20;`, `&#32;`, and `&nbsp;` to normal spacing. To discuss one
  intentionally, write its spoken form, such as "backslash n".

- For supplied text, preserve every word and punctuation mark in order while
  translating presentation syntax into speech.
- For a requested summary or explanation, write natural speech with the same
  meaning.
- For tables, state the headers once and read each row as labeled values.

## Record

```sh
agent-voice speak "$RESPONSE_AS_TEXT" --controls
```

For long text, create a unique file in the system temporary directory. The
operating system handles cleanup.

```sh
agent-voice speak --label "$LABEL" --controls < "$RESPONSE_AS_TEXT_FILE"
```

Set `LABEL` to a short subject. For an exact requested filename, replace
`--label "$LABEL"` with `--output "$PATH"`.

For speaker playback, add `-p` and continue after the result reports
`playback.state: "started"`. Add `--play-after SECONDS` to schedule it without
blocking.

## Deliver

Use [default.md](references/delivery/default.md) immediately after `speak`
returns a receipt with generation.state: "started"

## Remote delivery

Remote delivery requires Agent Voice 0.10.0 or newer. Run `agent-voice update`
if an installed version does not recognize `--viewer-base-url`.

When `delivery.browser_url` uses HTTPS, or generation runs on another machine,
return the HTTPS player URL as `[Listen](URL)`. This takes precedence over the
local delivery examples. Local file paths and desktop controls refer to the generating
machine; omit them from remote delivery. Do not use `-p` to play on that machine
unless the user asks. A localhost URL needs a configured private proxy and
`agent-voice config --viewer-base-url HTTPS_ORIGIN` before remote delivery works.

## Setup

If the command is unavailable:

```sh
uv tool install agent-voice
agent-voice setup
agent-voice controls install
```

## Resources

- CLI help: `agent-voice --help`
- Source and docs: [Agent Voice on GitHub](https://github.com/yoav0gal/agent-voice)
