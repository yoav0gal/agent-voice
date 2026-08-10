Use the exact block below whenever delivering a recording. Replace each
placeholder with its receipt value. Include every link that has a receipt
value. When a value is unavailable, remove the entire Markdown link, including
its label. Join the remaining links with ` · ` so no empty labels or dangling
separators appear.

Keep both `---` separators and the blank lines, spacing, wording, and inner code
fence exactly as shown. Send the block without the outer four-backtick fence.

````markdown

---

Agent Voice recording

Listen: [web player]($browser_url) · [media app]($file_uri) · [web audio]($audio_url)

Or run in the terminal

```sh
agent-voice play "$path" # returns when playback starts
```

---

````
