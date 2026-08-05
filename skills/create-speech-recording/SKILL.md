---
name: create-speech-recording
description: Turn text into speech with Agent Voice. Use for creating audio recordings and speaking text aloud.
---

# Create Speech Recording

Agent Voice works best in English. For another supported language, choose a
matching voice with `agent-voice voices` and pass `--voice` and `--lang`.

## Prepare

Set `RESPONSE` to the original text or Markdown. Set `TEXT` to its spoken form:

- For supplied text, preserve every word and punctuation mark in order while
  translating presentation syntax into speech.
- For a requested summary or explanation, write natural speech with the same
  meaning.
- For tables, state the headers once and read each row as labeled values.

## Record

```sh
agent-voice speak "$TEXT" --markdown "$RESPONSE"
```

For long text, use files:

```sh
agent-voice speak --label "$LABEL" --response-file "$RESPONSE_FILE" < "$TEXT_FILE"
```

Set `LABEL` to a short subject. For an exact requested filename, replace
`--label "$LABEL"` with `--output "$PATH"`.

Use the returned `path` to deliver the recording. For speaker playback, add
`--play` and complete after the result reports `played: true`.

## Deliver

Use one delivery mode:

1. If the current surface supports an audio player, render the returned `path`.
2. Otherwise render [recording-delivery.md](references/recording-delivery.md)
   with `path`, `file_uri`, `delivery.browser_url`, and `delivery.audio_url`
   from the command result.

## Setup

If the command is unavailable:

```sh
uv tool install agent-voice
agent-voice setup
```

## Resources

- CLI help: `agent-voice --help`
- Source and docs: [Agent Voice on GitHub](https://github.com/yoav0gal/agent-voice)
