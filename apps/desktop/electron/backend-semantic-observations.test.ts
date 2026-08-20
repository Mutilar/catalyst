import assert from 'node:assert/strict'

import { test } from 'vitest'

import { createSemanticObservationForwarder } from './backend-semantic-observations'

test('forwards only complete bounded semantic observation lines across chunk boundaries', () => {
  const forwarded: string[] = []
  const push = createSemanticObservationForwarder(line => forwarded.push(line))

  push('ordinary backend log\nHARNESS_TOOL_OBSER')
  push('VATION {"schema":"ae-catalyst-harness-tool-observation/1"}\n')
  push('PENGUIN_TEACHING_EVENT {"schema":"penguin-tool-intent-observed/1"}\n')

  assert.deepEqual(forwarded, [
    'HARNESS_TOOL_OBSERVATION {"schema":"ae-catalyst-harness-tool-observation/1"}\n',
    'PENGUIN_TEACHING_EVENT {"schema":"penguin-tool-intent-observed/1"}\n'
  ])
})

test('drops oversized and non-semantic backend stderr', () => {
  const forwarded: string[] = []
  const push = createSemanticObservationForwarder(line => forwarded.push(line))

  push(`HARNESS_TOOL_OBSERVATION ${'x'.repeat(9 * 1024)}\n`)
  push('LUCID {"private":"transport"}\n')
  push('ordinary backend log\n')

  assert.deepEqual(forwarded, [])
})
