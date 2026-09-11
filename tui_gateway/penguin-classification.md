Return exactly one glyph for the whole input.

| Glyph | Input |
|---|---|
| 🧠 | A direct LUCID request using one of the verbs below, with or without the lucid prefix, except MORPH. |
| 🤖 | An explicit executable invocation intended to run, rather than a question or quoted example. |
| 🔎 | MORPH always requires semantic reasoning. Also instructions to an agent, explanations, questions, planning, and mixed/uncertain intent. An instruction for an agent to assume a role is not a request to change the user's role. |

| Input | Output |
|---|---|
| git status | 🤖 |
| What does git status mean? | 🔎 |
| Sign in as EM | 🔎 |
| You are EM; sign in and inspect the task | 🔎 |
| MORPH | 🔎 |
| Explain what GET does | 🔎 |
| Run git status and explain the changes | 🔎 |