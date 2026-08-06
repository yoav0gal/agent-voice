If the current surface supports an audio player, render the returned `path`.
Otherwise, replace the available receipt values in this template. Remove viewer
links that do not have values. Send the result without the outer code fence.

````markdown
---

Agent Voice recording

Listen: [web player]($browser_url) · [media app]($file_uri) · [web audio]($audio_url)

Or run in the terminal

```sh
agent-voice play "$path"
```

---
````
