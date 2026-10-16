# T3 Code

Use this when T3 Code's `html_render` tool is available.

## Record

Omit `--wait`. When the speech service is running, the receipt includes
`delivery.stream_url`, so playback can start while generation continues.

## Deliver

If `delivery` has no `browser_url`, skip the page and give the `path` and
`agent-voice play "$path"` in the reply instead.

Set `RECORDING_NAME` to the basename of `path`. Set `AUDIO_SOURCE` to
`delivery.stream_url` when present, otherwise to `delivery.audio_url`. Set
`PLAYER_URL` to `delivery.browser_url`.

Replace the placeholders and call `html_render` with this page, the title
`$RECORDING_NAME`, and height `130`. Skip `html_preview`; the page is fixed. T3
shows the page above the written response, so do not mention it in the reply.

```html
<!doctype html>
<html lang="en"><head><meta charset="utf-8"></head><body>
<div style="box-sizing:border-box;width:min(100%,520px);color:var(--foreground)">
  <a href="$PLAYER_URL" target="_blank" rel="noopener" style="display:block;margin:0 0 .375rem;font:700 16px/1.2 var(--font-sans);letter-spacing:-.01em;overflow-wrap:anywhere;color:inherit;text-decoration:none">$RECORDING_NAME</a>
  <div style="display:flex;align-items:center;gap:12px;min-width:0">
    <audio controls preload="auto" src="$AUDIO_SOURCE" onerror="document.getElementById('fallback').hidden=false" style="display:block;min-width:0;width:100%;height:42px"></audio>
    <svg viewBox="0 0 100 100" role="img" aria-label="Agent Voice" style="display:block;flex:0 0 42px;width:42px;height:42px;fill:none;stroke:#ff6037;stroke-width:4;stroke-linecap:round;stroke-linejoin:round">
      <path d="M8 52h4c3 0 3-7 6-7s3 13 6 13c4 0 4-25 8-25s5 35 10 35c5 0 5-37 10-37s4 31 8 31c3 0 3-16 6-16s3 6 6 6" style="stroke-width:4.5"/>
      <path d="M78 45q6 6 0 12"/>
      <path d="M86 40q10 12 0 24"/>
    </svg>
  </div>
  <p id="fallback" hidden style="margin:.5rem 0 0;font:13px/1.4 var(--font-sans);color:var(--muted-foreground)">This frame cannot reach the recording. <a href="$PLAYER_URL" target="_blank" rel="noopener" style="color:var(--accent)">Open the web player</a></p>
</div>
</body></html>
```
