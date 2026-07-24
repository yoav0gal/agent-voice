---
name: kokoro-speak
description: Use the Kokoro CLI for read-aloud requests, local speech recordings, voice discovery, readiness checks, or the localhost speech service.
---

# Kokoro CLI

Use the globally installed `kokoro` command. If it is unavailable on `PATH`, direct the user to the repository README for installation instead of guessing a checkout path.

Speak text and play it:

```sh
kokoro speak "Text to read" --play --json
```

Pipe long or shell-sensitive text through stdin:

```sh
printf '%s' "$VISIBLE_SCRIPT" | kokoro speak --format mp3 --json
```

Choose an output path, format, voice, or speed:

```sh
kokoro speak "A slower reading" \
  --voice bf_emma \
  --speed 0.85 \
  --output recording.opus
```

Use `wav`, `mp3`, `opus`, or `m4a`. Speed accepts `0.5` through `4.0`. Run `kokoro voices` to list installed voices.

Prepare or diagnose the local runtime:

```sh
kokoro setup
kokoro doctor --json
```

Use the default `--service auto` for synthesis. Pass `--service required` to require the localhost service or `--service off` to force embedded inference.

Start the optional localhost API with:

```sh
kokoro serve
```

When `--json` is present, parse the final stdout line. Return its absolute `path`. Report completed playback only when `played` is `true`.

Run `kokoro <command> --help` for the complete option list.
