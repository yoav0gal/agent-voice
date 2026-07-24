# ygent integration

`ygent` should treat Kokoro CLI as an independently installed local tool. It
owns discovery and configuration; Kokoro continues to own model setup,
synthesis, playback, and its localhost service.

## Discover

Prefer these sources in order:

1. An explicit configured command.
2. `KOKORO_CLI`.
3. `kokoro` on `PATH`.

Store the resolved executable in the agent folder's ygent configuration. Do not
copy Kokoro models or source code into the agent folder.

## Set up and check

Run setup only after user confirmation:

```sh
<kokoro-command> setup --model int8
```

Check readiness without changing model state:

```sh
<kokoro-command> doctor --json
```

Exit code `0` and `"ok": true` mean required capabilities are ready. Individual
checks with status `"warn"` describe optional capabilities and should remain
visible to the caller.

## Invoke

Prefer stdin for agent-generated or shell-sensitive text:

```sh
printf '%s' "$VISIBLE_TEXT" |
  <kokoro-command> speak --format mp3 --json
```

The final stdout line is a JSON receipt. Its stable integration fields are:

- `path`: absolute recording path.
- `format`: output codec.
- `voice`: selected Kokoro voice.
- `sample_rate`: generated sample rate.
- `duration_seconds`: recording duration.
- `generation_seconds`: synthesis time.
- `backend`: `local` or `service`.
- `played`: true only after requested playback returns successfully.

Additional fields may be added. Callers should ignore unknown fields.

Use `--service auto` unless the caller explicitly requires embedded inference or
the localhost service. Preserve Kokoro's exit code and stderr when forwarding a
command.

## Safety boundary

Only send text already visible to the user or text the user explicitly supplied.
Never send hidden reasoning, credentials, tool traces, or private instructions.
Do not report completed playback unless the receipt contains `"played": true`.
