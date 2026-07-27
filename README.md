# Agent Voice

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/brand/agent-voice-logo-voiceprint-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="assets/brand/agent-voice-logo-voiceprint.svg">
  <img src="assets/brand/agent-voice-logo-voiceprint.svg" alt="Agent Voice logo" width="720">
</picture>

https://github.com/user-attachments/assets/975dcfd0-17ec-4912-b3b1-ec084077f858

Local text-to-speech for people and AI agents, powered by
[Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) (only English is supported).

Agent Voice creates WAV, MP3, Opus, or M4A recordings on macOS, Linux, and
Windows without an API key.

Prebuilt dependencies cover macOS arm64/x64, Linux x64, and Windows x64.
Linux arm64 currently needs a C build toolchain for miniaudio. Native Windows
arm64 lacks an `imageio-ffmpeg` wheel; use x64 Python under Windows emulation.

## Quick start

```sh
uv tool install agent-voice
agent-voice setup
agent-voice speak "Hello from Agent Voice." --play
```

`agent-voice setup` downloads and verifies the speech model.

## How to use

```sh
# See every recording option
agent-voice speak --help

# Create a recording
agent-voice speak "The build is finished."

# Play an existing recording
agent-voice play "/absolute/path/recording.mp3"

# Create an MP3 with a readable filename
agent-voice speak "Here is your summary." --format mp3 --label summary

# Choose a voice, speed, and exact output
agent-voice speak "A slower reading." \
  --voice bf_emma --speed 0.85 --output recording.opus

# Safely pass agent text through stdin
printf '%s' "$VISIBLE_TEXT" |
  agent-voice speak --format mp3
```

Every `agent-voice speak` command prints one machine-readable JSON receipt
containing the recording's absolute `path`, percent-encoded `file_uri`, audio
metadata, and a `delivery` object with `browser_url`, `audio_url`,
`recording_path`, and `fallback_markdown`.

Agent Voice stores the recording plus private transcript metadata in its managed
recordings directory. A lightweight localhost viewer renders the branded player
document—with the recording name, native audio controls, and response text—and
serves the actual WAV, MP3, Opus, or M4A recording. It starts automatically on
port `8779`, or on a free port when `8779` is occupied.

Agents use exactly two delivery routes:

1. Render `path` with the current surface's native audio player.
2. Otherwise return `delivery.fallback_markdown` unchanged:

   ````markdown
   Agent Voice recording recording.mp3
   Listen: [web player](http://127.0.0.1:8779/player/recording.html) · [media app](file:///absolute/path/recording.mp3) · [web audio](http://127.0.0.1:8779/recordings/recording.mp3)
   ```sh
   agent-voice play "/absolute/path/recording.mp3"
   ```
   ````

The viewer prefers port `8779` so links survive restarts. If that port is
occupied, it selects a free port and reports it in the receipt. The web player
renders the complete branded document, the media-app link opens the local file
with the operating system default, and web audio serves the recording directly
over HTTP.

The virtual player URL uses the recording name with an `.html` extension. If
that name already belongs to another format, Agent Voice adds `-2`, `-3`, and
so on.

Manage the lightweight viewer explicitly when needed:

```sh
agent-voice viewer start
agent-voice viewer stop
```

`--output` still writes the exact requested path. For HTTP delivery, Agent
Voice copies that audio into the managed recordings directory instead of
serving arbitrary filesystem paths or creating symlinks.

Explore the available voices and models, manage defaults, or check that Agent
Voice is ready:

```sh
agent-voice voices
agent-voice models
agent-voice config --voice bf_emma --speed 1.15
agent-voice doctor --json
```

## Defaults

Run `agent-voice config` to view the active persisted settings and their
configuration file.

| Setting | Built-in default | Save as default | Override once |
| --- | --- | --- | --- |
| Voice | `af_heart` | `config --voice NAME` | `speak --voice NAME` |
| Speed | `1.0×` | `config --speed NUMBER` | `speak --speed NUMBER` |
| Audio format | MP3 | `config --format FORMAT` | `speak --format FORMAT` |
| Recording directory | Agent Voice's `recordings/` directory | `config --output-dir DIR` | `speak --output-dir DIR` |
| Service | `timed` for `10` minutes | `config --service MODE [--service-timeout MINUTES]` | `speak --service MODE [--service-timeout MINUTES]` |

`on` leaves the service running, `off` uses embedded inference, and `timed`
stops the service after the configured number of idle minutes.

The service setting is stored as one object. Timed mode includes its duration:

```json
{
  "service": {
    "mode": "timed",
    "timeout_minutes": 10
  }
}
```

## Agent skills

[View Agent Voice on skills.sh](https://skills.sh/b/yoav0gal/agent-voice).

```sh
# Create speech recordings or read text aloud
npx skills add yoav0gal/agent-voice --skill agent-voice --global --agent codex --yes

# Add audio to explicitly opted-in written responses
npx skills add yoav0gal/agent-voice --skill spoken-responses --global --agent codex --yes
```

Use `--agent '*'` instead of `--agent codex` to install the same skills for all
agent destinations recognized by the skills CLI.

## Local speech API

```sh
agent-voice serve

curl http://127.0.0.1:8765/v1/audio/speech \
  -H 'Content-Type: application/json' \
  -d '{"input":"The task is complete.","voice":"af_heart","response_format":"mp3"}' \
  --output speech.mp3
```

The speech API binds only to localhost. It is separate from the lightweight
recording viewer. `agent-voice speak` uses the speech API automatically when
available and falls back to embedded inference.
