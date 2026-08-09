

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/brand/agent-voice-logo-voiceprint-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="assets/brand/agent-voice-logo-voiceprint.svg">
  <img src="assets/brand/agent-voice-logo-voiceprint.svg" alt="Agent Voice logo" width="720">
</picture>

---

![Agent Voice launch video](assets/agent-voice-launch.gif)

Agent Voice gives AI agents the ability to create local speech recordings.

AI agents produce useful work, but they still communicate mostly through text.
Every response competes for a developer's visual attention, so valuable work is
often skimmed or missed.

My initial use case was listening alongside the text: text-to-speech for coding
agents such as Codex and Claude Code.

The larger idea is simple: audio should be a first-class medium for agents.

Agent Voice runs locally, uses
[Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M), and requires no API
key. English is the best-supported language. The bundled 54-voice catalog also
covers Japanese, Mandarin Chinese, Spanish, French, Hindi, Italian, and
Brazilian Portuguese, though quality varies.

[Check them out here](https://rewind.ai/voices/).

## Install and setup

Install the CLI and download the speech model:

```sh
uv tool install agent-voice
agent-voice setup
```

### Choose a delivery method

For desktop applications, the recommended way is to use the `-desktop` skills.
They embed a media player directly in the answer and currently support
Antigravity, Codex, and OpenCode:

```sh
npx skills add yoav0gal/agent-voice --skill create-speech-recording-desktop --global
npx skills add yoav0gal/agent-voice --skill spoken-response-desktop --global
```

For CLIs and portable Markdown delivery, install the normal skills:

```sh
npx skills add yoav0gal/agent-voice --skill create-speech-recording --global
npx skills add yoav0gal/agent-voice --skill spoken-response --global
```

The normal skills deliver three links:

- **web player** — the recommended option; open it in an application browser.
  In coding-agent apps, this view includes the written answer too.
- **media app** — opens the linked recording in your default media app.
- **web audio** — opens the audio directly and should start playing
  automatically.

Test it:

```sh
agent-voice speak "Hello from Agent Voice." --play
```

## Skills

Agent Voice includes two skills:

- **create-speech-recording** turns supplied text into audio. Use it when you
  want an agent to create a recording or read something aloud.
- **spoken-response** creates an audio version of an agent's written response.
  Use it when you want to listen to a long answer instead of reading it.

Each skill also has a **`-desktop`** version that does the same job but
delivers the recording through a player embedded in the desktop app.

These skills are starting points. Copy them, edit them, and make them yours.
You can change delivery wording, recording defaults, playback behavior, or
when the agent should offer audio.

Each skill owns its delivery references. The CLI returns structured facts; the
installed skill decides how those facts are presented.

## CLI

The CLI provides small primitives that agents can combine. Run
`agent-voice COMMAND --help` for the full options of any command.

| Command | What it does |
| --- | --- |
| `setup` | Download and verify speech model assets. |
| `speak` | Turn text or stdin into a recording. |
| `play` | Play an existing local recording. |
| `voices` | List supported language tags and voices. |
| `models` | List speech models and variants. |
| `config` | View or change persistent defaults. |
| `doctor` | Check that Agent Voice is ready. |
| `viewer start\|stop` | Manage the local recording viewer. |
| `serve` | Start the localhost speech API. |

### Speak

```sh
# Positional text
agent-voice speak "The build is finished."

# Agent output through stdin
printf '%s' "$TEXT" | agent-voice speak --label build-summary

# Spoken response text and written response Markdown in one command
agent-voice speak "$RESPONSE_AS_TEXT" \
  --markdown "$RESPONSE_AS_MARKDOWN" --label response

# Use separate files for a long spoken response and its written Markdown
agent-voice speak --response-file "$RESPONSE_AS_MARKDOWN_FILE" \
  < "$RESPONSE_AS_TEXT_FILE"

# Choose the output and delivery
agent-voice speak "Here is your summary." \
  --voice bf_emma --speed 1.2 --format mp3 --play
```

| Option | Purpose |
| --- | --- |
| `-o, --output PATH` | Write to an exact path. |
| `--label TEXT` | Set the managed filename prefix. |
| `--markdown TEXT` | Show an inline Markdown response in the viewer. |
| `--response-file PATH` | Show a Markdown response in the browser viewer. |
| `--output-dir DIR` | Choose the managed output directory. |
| `-f, --format FORMAT` | Use `wav`, `mp3`, `opus`, or `m4a`. |
| `-v, --voice NAME` | Select a voice. |
| `--lang TAG` | Set the language tag (default: `en-us`). |
| `--speed NUMBER` | Set pitch-preserving playback speed. |
| `--play` | Play the recording after creation. |
| `--service on\|off\|timed` | Control background inference. |
| `--service-timeout MINUTES` | Set the idle timeout for timed mode. |
| `--model-id ID`, `--variant NAME` | Select a model and build. |

`speak` prints one JSON receipt with the absolute recording path, file URI,
audio metadata, playback status, and available viewer links. This makes the
command reliable for both people and agents.

### Configure defaults

```sh
# Show current defaults
agent-voice config

# Set your preferred voice, speed, format, and output directory
agent-voice config --voice bf_emma --speed 1.15 --format mp3 --output-dir ./recordings

# Restore built-in defaults
agent-voice config --reset
```

The same values can be overridden per recording with `speak`. Service modes are
`on` for a persistent local service, `off` for embedded inference, and `timed`
to stop the service after an idle timeout.

### Discover and diagnose

```sh
agent-voice voices
agent-voice models
agent-voice doctor
agent-voice doctor --json
```

`voices` groups each installed voice under its supported `--lang` tag. Select a
pair with `agent-voice speak --lang TAG --voice VOICE "Text"`.

Use `--json` with `voices`, `models`, `config`, or `doctor` when another tool or
agent will consume the result.

### Play and view recordings

```sh
agent-voice play "/absolute/path/recording.mp3"
agent-voice viewer start
agent-voice viewer stop
```

The lightweight viewer starts automatically when needed and serves only local
recordings. It prefers `http://127.0.0.1:8779` and selects a free port if that
port is unavailable. Each managed recording keeps an editable `.txt` source
beside it. At startup and every six hours, the viewer removes owned audio older
than four days and 18 hours; files without Agent Voice source, transcript, and
language metadata are left alone. Opening a player or audio URL regenerates
missing audio from its source with the original language and current voice and
speed.

> 🗒️ The viewer is a workaround for agent surfaces that do not support embedded
audio. I expect native text-to-speech to become common across these platforms,
which would be a better solution. For now, the viewer keeps playback and the
written response together in a local page. 🗒️

### Local speech API

```sh
agent-voice serve

curl http://127.0.0.1:8765/v1/audio/speech \
  -H 'Content-Type: application/json' \
  -d '{"input":"The task is complete.","voice":"af_heart","response_format":"mp3"}' \
  --output speech.mp3
```

The API binds to localhost. `speak` uses it when available and falls back to
embedded inference.

### Platform limitations

Prebuilt dependencies support macOS arm64/x64, Linux x64, and Windows x64.
Linux arm64 requires a C build toolchain for miniaudio. On Windows arm64, use
x64 Python under emulation.
