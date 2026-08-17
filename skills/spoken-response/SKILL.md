---
name: spoken-response
description: Read an assistant response aloud with Agent Voice. Use when the user requests a spoken response, the previous response as audio, or spoken responses for a thread.
---

# Spoken Response

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
   agent-voice speak "$RESPONSE_AS_TEXT" --label "$LABEL"
   ```

   For long responses, use temporary files outside the workspace and remove them
   afterward:

   ```sh
   agent-voice speak --label "$LABEL" < "$RESPONSE_AS_TEXT_FILE"
   ```

5. Place the audio above the written response or `Previous` confirmation using
   [default.md](references/delivery/default.md).

For speaker playback, add `-p` and continue after the result reports
`playback.state: "started"`. Add `--play-after SECONDS` to schedule it without
blocking. On synthesis failure, send the written response with a brief
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
