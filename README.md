# Agent Voice

<img src="assets/brand/agent-voice-logo-voiceprint.png" alt="Agent Voice logo" width="720">


Local text-to-speech for people and AI agents, powered by
[Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) (only English is supported).

Agent Voice creates WAV, MP3, Opus, or M4A recordings on macOS, Linux, and Windows without an API
key.

[🔊 Listen to this introduction (MP3)](assets/agent-voice-intro.mp3?raw=1)

## Quick start

```sh
uv tool install agent-voice
agent-voice setup
agent-voice speak "Hello from Agent Voice." --play --json
```

## How to use

```sh
# See every recording option
agent-voice speak --help

# Create a recording
agent-voice speak "The build is finished."

# Create an MP3 with a readable filename
agent-voice speak "Here is your summary." --format mp3 --label summary

# Choose a voice, speed, and exact output
agent-voice speak "A slower reading." \
  --voice bf_emma --speed 0.85 --output recording.opus

# Safely pass agent text through stdin
printf '%s' "$VISIBLE_TEXT" |
  agent-voice speak --format mp3 --json
```

`--json` prints a machine-readable receipt containing the recording's absolute
`path` and audio metadata.

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
| Audio format | WAV | `config --format FORMAT` | `speak --format FORMAT` |
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
# Read text aloud when requested
npx skills add yoav0gal/agent-voice --skill read-aloud --global --agent codex --yes

# Add audio to explicitly opted-in written responses
npx skills add yoav0gal/agent-voice --skill spoken-responses --global --agent codex --yes
```

## Local API

```sh
agent-voice serve

curl http://127.0.0.1:8765/v1/audio/speech \
  -H 'Content-Type: application/json' \
  -d '{"input":"The task is complete.","voice":"af_heart","response_format":"mp3"}' \
  --output speech.mp3
```

The service binds only to localhost. `agent-voice speak` uses it automatically
when available and falls back to embedded inference.
