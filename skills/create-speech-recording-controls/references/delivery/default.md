Use the exact block below whenever delivering a recording. Replace each
placeholder with its receipt value. If `delivery.controls` is unavailable, use
the normal portable delivery instead.

Set `$restart`, `$back`, `$toggle`, `$forward`, `$slower`, and `$faster` from
the matching keys in `delivery.controls`. Include the fallback row only when
`$browser_url` exists.

Keep both `---` separators and the blank lines. Send the block without the
outer four-backtick fence.

````markdown

---

Agent Voice recording

Controls: [↺ Restart]($restart) · [↶ 10s]($back) · [⏯ Play / pause]($toggle) · [10s ↷]($forward) · [🐢 Slower]($slower) · [Faster 🐇]($faster)

Fallback: [open web player]($browser_url)

---

````
