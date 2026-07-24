# Kokoro CLI

[![skills.sh](https://skills.sh/b/yoav0gal/kokoro-cli)](https://skills.sh/yoav0gal/kokoro-cli)

A small, offline text-to-speech tool for people and AI agents. It runs Kokoro-82M locally through ONNX, creates WAV, MP3, Opus, or M4A recordings, can play them on the host machine, and exposes an optional localhost HTTP API.

Kokoro CLI currently targets macOS and Linux.

## Install globally

Kokoro CLI supports Python 3.11 through 3.13. Install it from PyPI with [`uv`](https://docs.astral.sh/uv/) to keep the command in an isolated tool environment:

```sh
uv tool install kokoro-cli
```

[`pipx`](https://pipx.pypa.io/) works too:

```sh
pipx install kokoro-cli
```

To upgrade an existing installation:

```sh
uv tool upgrade kokoro-cli
```

If `uv` reports that its tool directory is not on `PATH`, run:

```sh
uv tool update-shell
```

Open a new terminal, then prepare and verify Kokoro:

```sh
kokoro setup
kokoro doctor --json
kokoro speak "Hello. This is Kokoro speaking locally." --play --json
```

`kokoro setup` downloads the compact int8 model and voices once, approximately 121 MB total. Downloads are locked for concurrent processes and verified with pinned SHA-256 hashes. Speech synthesis is offline after setup.

The global `kokoro` command works from any directory for the current user. To install the latest unreleased GitHub version instead:

```sh
uv tool install --force "git+https://github.com/yoav0gal/kokoro-cli.git"
```

### Optional system tools

- Install `ffmpeg` for MP3, Opus, M4A, and speech speeds above 2x. WAV works without it.
- Use the built-in `afplay` on macOS or install `ffplay` for local playback.

On macOS:

```sh
brew install uv ffmpeg
```

On Linux, install `uv` and `ffmpeg` with the methods appropriate for your distribution.

## CLI

```sh
# Text argument, then play it
kokoro speak "The build is finished." --play

# Agent-friendly stdin and JSON result
printf '%s' "Here is your summary." | kokoro speak --format mp3 --json

# Select voice, speed, and output codec from the file extension
kokoro speak "A slower reading." --voice bf_emma --speed 0.85 -o recording.opus

# Go beyond Kokoro's native limit with pitch-preserving tempo adjustment
kokoro speak "A very fast reading." --speed 4.0 --play

# Discover voices
kokoro voices

# Inspect or update persistent speech defaults
kokoro config --json
kokoro config --voice bf_emma --speed 1.15

# Check runtime, models, codecs, playback, and optional service health
kokoro doctor --json

# Higher-fidelity model variants with larger downloads
kokoro setup --model fp16
kokoro setup --model full
```

Run `kokoro <command> --help` for the complete option list.

Generated files use the platform user-data directory unless `--output` is supplied:

- macOS: `~/Library/Application Support/kokoro/recordings`
- Linux: `${XDG_DATA_HOME:-~/.local/share}/kokoro/recordings`

Set `KOKORO_HOME`, `KOKORO_MODEL_DIR`, or `KOKORO_RECORDING_DIR` to choose explicit locations.

The built-in voice is `af_heart` at `1.0x`. `kokoro config` stores machine-level voice and speed defaults in `config.json` under `KOKORO_HOME`; explicit `speak` flags take precedence. Run `kokoro config --reset` to restore the built-ins.

The default `int8` model is the lightweight choice; `fp16` and `full` are available for A/B listening. Speech speed ranges from `0.5` to `4.0`. Speeds through `2.0` are generated directly by Kokoro; higher speeds use FFmpeg to accelerate the result while preserving pitch.

### Service selection

`speak` has explicit service semantics:

- `--service auto` is the default. It uses a healthy localhost service and falls back to embedded inference.
- `--service required` fails if the configured service is unavailable.
- `--service off` always uses embedded inference.

Set `KOKORO_SERVICE_URL` or pass `--service-url` to select another localhost port. Remote and HTTPS URLs are rejected because the service is intentionally local.

## Local service for agents

Start the service:

```sh
kokoro serve
```

Use it from another terminal:

```sh
curl -sS http://127.0.0.1:8765/health

curl -sS http://127.0.0.1:8765/v1/audio/speech \
  -H 'Content-Type: application/json' \
  -d '{"input":"Your agent has finished the task.","voice":"af_heart","response_format":"mp3"}' \
  -o agent-message.mp3
```

The API also accepts `"play": true` to play the result on the host. `GET /health` returns the service identity, Kokoro CLI version, active model variant, and readiness. Successful speech responses include `X-Kokoro-*` headers for voice, sample rate, duration, generation time, and playback state.

## Agent skill

The repository includes the standalone [`read-aloud`](https://github.com/yoav0gal/kokoro-cli/tree/main/skills/read-aloud) skill. Install it globally for Codex directly from GitHub through [`skills`](https://skills.sh/):

```sh
npx skills add yoav0gal/kokoro-cli --skill read-aloud --global --agent codex --yes
```

To inspect the repository's available skills without installing:

```sh
npx skills add yoav0gal/kokoro-cli --list
```

The skill and CLI are separate installables:

- `skills` installs only the `read-aloud` agent instructions from `skills/read-aloud`.
- The skill invokes the global `kokoro` command and installs `kokoro-cli` from PyPI when that command is unavailable.
- No local clone of this repository is required after installation.

Restart the agent after installation if it does not reload skills automatically. For another supported agent, replace `codex` in the install command with its agent name.

## Use from a checkout

The repository wrapper remains available for development without a global installation:

```sh
git clone https://github.com/yoav0gal/kokoro-cli.git
cd kokoro-cli
./kokoro setup
./kokoro doctor --json
./kokoro speak "Running from a checkout." --json
```

The wrapper creates an isolated environment through `uv` and keeps models and recordings inside that checkout.

## Architecture

```text
agent or human (visible text only)
    │
    ├── kokoro speak ── health check / fallback ──┐
    │                                             │
    └── POST /v1/audio/speech ────────────────────┤
                                                  ▼
                         one shared SpeechEngine
                         Kokoro ONNX + voice styles
                                    │ 24 kHz mono samples
                                    ▼
                         WAV writer / ffmpeg codecs
                                    │
                         file, HTTP bytes, or playback
```

The HTTP layer uses Python's standard library. Model inference is serialized behind a lock because a single local voice service values predictable resource use more than request fan-out.

The directly openable product record at [`docs/capabilities.html`](https://github.com/yoav0gal/kokoro-cli/blob/main/docs/capabilities.html) distinguishes current, verified, planned, and out-of-scope behavior.

## ygent integration

Kokoro CLI exposes a stable machine-facing contract for `ygent` and other orchestrators:

```sh
kokoro setup --model int8
kokoro doctor --json
printf '%s' "Visible text" | kokoro speak --format mp3 --json
kokoro voices --json
```

The repository-owned integration manifest is [`integrations/ygent.json`](https://github.com/yoav0gal/kokoro-cli/blob/main/integrations/ygent.json). The complete adapter contract, discovery rules, exit behavior, and JSON receipt fields are documented in [`docs/ygent-integration.md`](https://github.com/yoav0gal/kokoro-cli/blob/main/docs/ygent-integration.md).

## Boundaries

Kokoro CLI does not expose a remote server, cloud TTS, or speech-to-text. Other products can compose with the public CLI and localhost HTTP contracts documented above.

## Model and licenses

- Kokoro-82M weights: Apache 2.0.
- `kokoro-onnx` runtime: MIT.
- Model assets come from the `model-files-v1.0` release of `thewh1teagle/kokoro-onnx`.
