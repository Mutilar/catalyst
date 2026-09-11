Format the user's LUCID request as one canonical action string.

| Glyph | Meaning |
|---|---|
| ➡️ 🧠 | LUCID action |
| ⚡ | Verb, uppercase |
| 🎯 | Noun, uppercase |
| ⚙️ | Argument; preserve literal values and quote strings |
| 🔎 | Short action label |

Separate atoms with exactly ` · `. Omit the argument atom when absent. Preserve the requested operation, target, and arguments. Return only the action string.

| Input | Output |
|---|---|
| SHOW PULSE | ➡️ 🧠 · ⚡ SHOW · 🎯 PULSE · 🔎 Show pulse |
| SHOW URL "https://example.com/" | ➡️ 🧠 · ⚡ SHOW · 🎯 URL · ⚙️ "https://example.com/" · 🔎 Open URL |
| SHOW APP "macos-shell" | ➡️ 🧠 · ⚡ SHOW · 🎯 APP · ⚙️ "macos-shell" · 🔎 Open macOS Shell |
| lucid get role | ➡️ 🧠 · ⚡ GET · 🎯 ROLE · 🔎 Inspect role |