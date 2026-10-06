---
name: spoken-response-desktop
description: Read and embed an assistant response aloud in Codex Desktop, Antigravity App, or OpenCode Desktop.
---

# Spoken Response Desktop

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

   - **Speech-ready:** use plain text, not serialized text. Convert literal `\n`,
     `\r`, `\t`, `&#x20;`, `&#32;`, and `&nbsp;` to normal spacing. To discuss
     one intentionally, write its spoken form, such as "backslash n".
   - **Fidelity:** preserve wording and order; do not summarize or rephrase.
   - **Non-prose:** translate formatting and read tables naturally. Explain code
     or visuals when useful; otherwise briefly introduce them ("Here is the
     code" or "See the diagram below") and continue.
3. Set `LABEL` to `SR`. When a thread title is already available, use
   `<title> - SR`.
4. Create the recording with the configured voice, speed, and format. On
   Antigravity App, follow the special
   [recording and delivery instructions](references/delivery/antigravity.md).

   ```sh
   agent-voice speak "$RESPONSE_AS_TEXT" --label "$LABEL" --wait
   ```

   For long responses, create a unique file in the system temporary directory.
   The operating system handles cleanup.

   ```sh
   agent-voice speak --label "$LABEL" --wait < "$RESPONSE_AS_TEXT_FILE"
   ```

   On OpenCode Desktop, omit `--wait` and go straight to the delivery reference.

5. Place the audio above the written response or `Previous` confirmation. Use
   the first matching delivery reference:
   - Antigravity App: [antigravity.md](references/delivery/antigravity.md)
   - OpenCode Desktop: [opencode-desktop.md](references/delivery/opencode-desktop.md)
   - Other (Codex Desktop): [default.md](references/delivery/default.md)

For speaker playback, add `-p` and continue after the result reports
`playback.state: "started"`. Add `--play-after SECONDS` to schedule it without
blocking. On synthesis failure, send the written response with a brief
failure note.

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

If `agent-voice` is unavailable:

```sh
uv tool install agent-voice
agent-voice setup
```

## Resources

- CLI help: `agent-voice --help`
- Source and docs: [Agent Voice on GitHub](https://github.com/yoav0gal/agent-voice)
