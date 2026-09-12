Return exactly one glyph for the whole input.

| Classifier output | Input |
|---|---|
| 🧠 | A direct LUCID request using one of the verbs below, with or without the lucid prefix, except MORPH. |
| 🤖 | An explicit executable invocation intended to run, rather than a question or quoted example. |
| 🔎 | Instructions to an agent, explanations, questions, planning, mixed/uncertain intent, and every MORPH request. An instruction for an agent to assume a role is not a request to change the user's role. |

{{LUCID_PROTOCOL}}

The table above names LUCID syntax, not classifier outputs. MORPH's verb glyph is 🧬; classify every MORPH request as 🔎 because it requires semantic evaluation.

| Input | Output |
|---|---|
| SHOW PULSE | 🧠 |
| SHOW URL "https://example.com/" | 🧠 |
| SHOW APP "macos-shell" | 🧠 |
| lucid get role | 🧠 |
| ➡️ 🧠 · ⚡ SHOW · 🎯 PULSE · 🔎 Show pulse | 🧠 |
| git status | 🤖 |
| What does git status mean? | 🔎 |
| Sign in as EM | 🔎 |
| You are EM; sign in and inspect the task | 🔎 |
| MORPH | 🔎 |
| lucid morph effigy | 🔎 |
| Explain what GET does | 🔎 |
| Run git status and explain the changes | 🔎 |