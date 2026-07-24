# Kokoro CLI

[![skills.sh](https://skills.sh/b/yoav0gal/kokoro-cli)](https://skills.sh/yoav0gal/kokoro-cli)

Offline text-to-speech for people and AI agents. Kokoro CLI runs Kokoro-82M locally, creates WAV, MP3, Opus, or M4A recordings, plays them on the host, and exposes an optional localhost API.

Currently supported on macOS and Linux with Python 3.11–3.13.

## Quick start

Install the CLI from PyPI:

```sh
uv tool install kokoro-cli
kokoro setup
kokoro speak "Hello from Kokoro." --play --json
```

`kokoro setup` downloads and verifies the default model and voices, about 121 MB. Synthesis is offline after setup.

Install [`uv`](https://docs.astral.sh/uv/) and optional FFmpeg on macOS with:

```sh
brew install uv ffmpeg
```

On Linux, use your package manager for FFmpeg. WAV works without it; MP3, Opus, M4A, and speeds above 2x require it. `pipx install kokoro-cli` is also supported.

## Common commands

```sh
# Create and play a recording
kokoro speak "The build is finished." --play

# Pipe agent-friendly input and return a JSON receipt
printf '%s' "Here is your summary." | kokoro speak --format mp3 --json

# Choose a voice, speed, format, and output path
kokoro speak "A slower reading." --voice bf_emma --speed 0.85 -o recording.opus

# Discover voices and manage persistent defaults
kokoro voices
kokoro config --json
kokoro config --voice bf_emma --speed 1.15
kokoro config --reset

# Verify the installation
kokoro doctor --json
```

The default is `af_heart` at `1.0x`; supported speeds are `0.5`–`4.0`. Run `kokoro <command> --help` for all options.

Recordings and models use the platform user-data directory. Override it with `KOKORO_HOME`, `KOKORO_MODEL_DIR`, or `KOKORO_RECORDING_DIR`.

## Agent skill

Install the standalone [`read-aloud`](https://skills.sh/yoav0gal/kokoro-cli/read-aloud) skill globally for Codex:

```sh
npx skills add yoav0gal/kokoro-cli --skill read-aloud --global --agent codex --yes
```

The skill is installed separately from this repository. It invokes the global `kokoro` command and installs `kokoro-cli` from PyPI when needed.

## Local API

Start the localhost service:

```sh
kokoro serve
```

Then request speech through the OpenAI-shaped endpoint:

```sh
curl -sS http://127.0.0.1:8765/v1/audio/speech \
  -H 'Content-Type: application/json' \
  -d '{"input":"Your agent has finished the task.","voice":"af_heart","response_format":"mp3"}' \
  -o agent-message.mp3
```

The service only accepts localhost connections. `speak` uses a healthy service automatically and falls back to embedded inference; use `--service required` or `--service off` for strict behavior.

## Development

```sh
git clone https://github.com/yoav0gal/kokoro-cli.git
cd kokoro-cli
./kokoro setup
./kokoro doctor --json
uv run --frozen pytest -q
```

The checkout wrapper keeps its environment, models, and recordings inside the repository.

## More

- [Capabilities and product boundaries](https://github.com/yoav0gal/kokoro-cli/blob/main/docs/capabilities.html)
- [ygent integration contract](https://github.com/yoav0gal/kokoro-cli/blob/main/docs/ygent-integration.md)
- [Read-aloud skill source](https://github.com/yoav0gal/kokoro-cli/blob/main/skills/read-aloud/SKILL.md)
- [Issues](https://github.com/yoav0gal/kokoro-cli/issues)

Kokoro-82M weights are Apache 2.0, `kokoro-onnx` is MIT, and model assets come from the `model-files-v1.0` release of `thewh1teagle/kokoro-onnx`. See [third-party notices](https://github.com/yoav0gal/kokoro-cli/blob/main/THIRD_PARTY_NOTICES.md).
