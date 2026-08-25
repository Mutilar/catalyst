import assert from 'node:assert/strict'

import { test } from 'vitest'

import { createSemanticObservationForwarder } from './backend-semantic-observations'

test('forwards only complete bounded semantic observation lines across chunk boundaries', () => {
  const forwarded: string[] = []
  const push = createSemanticObservationForwarder(line => forwarded.push(line))

  push('ordinary backend log\nCATALYST_TOOL_OBSER')
  push('VATION {"schema":"ae-catalyst-harness-tool-observation/1"}\n')
  push('PENGUIN_TEACHING_EVENT {"schema":"penguin-tool-intent-observed/1"}\n')
  push('⚠️ 🎼🐧 · 🔎 effigy-transfer-protected-identity-refused: protected identity reached transfer\n')
  push('⚠️ 🎼🐧 · 🔎 penguin-model-connect-failed\n')
  push('⚠️ 🎼🐱 · 🔎 penguin-model-connect-failed\n')

  assert.deepEqual(forwarded, [
    'CATALYST_TOOL_OBSERVATION {"schema":"ae-catalyst-harness-tool-observation/1"}\n',
    'PENGUIN_TEACHING_EVENT {"schema":"penguin-tool-intent-observed/1"}\n',
    '⚠️ 🎼🐧 · 🔎 effigy-transfer-protected-identity-refused: protected identity reached transfer\n',
    '⚠️ 🎼🐧 · 🔎 penguin-model-connect-failed\n',
    '⚠️ 🎼🐱 · 🔎 penguin-model-connect-failed\n'
  ])
})

test('drops oversized and non-semantic backend stderr', () => {
  const forwarded: string[] = []
  const push = createSemanticObservationForwarder(line => forwarded.push(line))

  push(`CATALYST_TOOL_OBSERVATION ${'x'.repeat(9 * 1024)}\n`)
  push('LUCID {"private":"transport"}\n')
  push('ordinary backend log\n')

  assert.deepEqual(forwarded, [])
})
