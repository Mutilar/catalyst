import assert from 'node:assert/strict'

import { test } from 'vitest'

import { createSemanticObservationForwarder } from './backend-semantic-observations'
import { SIGNAL_WARNING } from './ae-glyphs.generated.js'
import { canonicalGestaltStream } from '../../shared/src/lucid-gestalt.js'

test('forwards only complete bounded semantic observation lines across chunk boundaries', () => {
  const forwarded: string[] = []
  const push = createSemanticObservationForwarder(line => forwarded.push(line))

  push('ordinary backend log\nCATALYST_TOOL_OBSER')
  push('VATION {"schema":"ae-catalyst-harness-tool-observation/1"}\n')
  push('PENGUIN_TEACHING_EVENT {"schema":"penguin-tool-intent-observed/1"}\n')
  const protectedIdentity = canonicalGestaltStream({
    signal: SIGNAL_WARNING,
    evidence: ['effigy-transfer-protected-identity-refused: protected identity reached transfer']
  })
  const connectFailed = canonicalGestaltStream({
    signal: SIGNAL_WARNING,
    evidence: ['penguin-model-connect-failed']
  })
  push(`${protectedIdentity}\n`)
  push(`${connectFailed}\n`)
  push(`${SIGNAL_WARNING} retired warning syntax\n`)

  assert.deepEqual(forwarded, [
    'CATALYST_TOOL_OBSERVATION {"schema":"ae-catalyst-harness-tool-observation/1"}\n',
    'PENGUIN_TEACHING_EVENT {"schema":"penguin-tool-intent-observed/1"}\n',
    `${protectedIdentity}\n`,
    `${connectFailed}\n`
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
