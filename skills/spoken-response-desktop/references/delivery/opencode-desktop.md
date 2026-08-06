# OpenCode Desktop

Set `PLAYER_ID` to a unique lowercase ID. Set `RECORDING_NAME` to the basename
of the returned `path`. Set `audio_url` to `delivery.audio_url`. Replace the
placeholders in the template. Render the HTML directly without the code fence.

```html
<div id="$PLAYER_ID" style="box-sizing:border-box;width:min(100%,520px);margin:0 0 1.125rem;color:CanvasText;color-scheme:light dark">
  <div style="margin:0 0 .375rem;font:700 16px/1.2 ui-sans-serif,system-ui,-apple-system,sans-serif;letter-spacing:-.01em;color:CanvasText">$RECORDING_NAME</div>
  <div style="display:flex;align-items:center;gap:12px;min-width:0">
    <audio controls preload="metadata" src="$audio_url" style="display:block;min-width:0;width:100%;height:42px">
      <a href="$audio_url">Play recording</a>
    </audio>
    <svg viewBox="0 0 100 100" role="img" aria-label="Agent Voice" style="display:block;flex:0 0 42px;width:42px;height:42px;fill:none;stroke:#ff6037;stroke-width:4;stroke-linecap:round;stroke-linejoin:round">
      <path d="M8 52h4c3 0 3-7 6-7s3 13 6 13c4 0 4-25 8-25s5 35 10 35c5 0 5-37 10-37s4 31 8 31c3 0 3-16 6-16s3 6 6 6" style="stroke-width:4.5"/>
      <path d="M78 45q6 6 0 12"/>
      <path d="M86 40q10 12 0 24"/>
    </svg>
  </div>
</div>
```
