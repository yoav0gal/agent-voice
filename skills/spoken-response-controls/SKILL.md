---
name: spoken-response-controls
description: Read an assistant response aloud with clickable Agent Voice playback controls. Use when the user explicitly requests controlled playback on a compatible desktop renderer.
---

# Spoken Response Controls

A spoken response reads the assistant response aloud without rewriting it.

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
2. Set `RESPONSE_AS_TEXT` to a read-aloud copy:
   - **Fidelity:** preserve wording and order; do not summarize or rephrase.
   - **Non-prose:** translate formatting and read tables naturally. Explain code
     or visuals when useful; otherwise briefly introduce them ("Here is the
     code" or "See the diagram below") and continue.
3. Set `LABEL` to `SR`. When a thread title is already available, use
   `<title> - SR`.
4. Create the recording with the configured voice, speed, and format:

   ```sh
   agent-voice speak "$RESPONSE_AS_TEXT" --label "$LABEL" --controls
   ```

   For long responses, use temporary files outside the workspace and remove them
   afterward:

   ```sh
   agent-voice speak --label "$LABEL" --controls < "$RESPONSE_AS_TEXT_FILE"
   ```

5. Place the controls above the written response or `Previous` confirmation using
   [default.md](references/delivery/default.md) immediately after `speak`
returns a receipt with generation.state: "started"

For speaker playback, add `-p` and continue after the result reports
`playback.state: "started"`. Add `--play-after SECONDS` to schedule it without
blocking. On synthesis failure, send the written response with a brief
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
