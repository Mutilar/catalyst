import { describe, expect, it } from 'vitest'

import {
  API_FAILURE_SCHEMA,
  apiIpcFailure,
  shouldRetryApiRequest,
  unwrapApiIpcResult
} from './api-ipc-failure'

describe('desktop API IPC failures', () => {
  it('projects connection resets without transport or framework implementation detail', () => {
    const cause = Object.assign(new Error('socket hang up'), { code: 'ECONNRESET' })

    expect(apiIpcFailure(cause)).toEqual({
      schema: API_FAILURE_SCHEMA,
      failure: {
        code: 'desktop-api-connection-reset',
        detail: 'desktop-api-connection-reset'
      }
    })
  })

  it('restores renderer rejection from the bounded failure envelope', () => {
    const failure = apiIpcFailure(new Error('404: route unavailable'))

    expect(() => unwrapApiIpcResult(failure)).toThrow('404: route unavailable')
    expect(unwrapApiIpcResult({ rows: [1] })).toEqual({ rows: [1] })
  })

  it('retries only idempotent reset reads', () => {
    const reset = Object.assign(new Error('socket hang up'), { code: 'ECONNRESET' })

    expect(shouldRetryApiRequest(reset, 'GET')).toBe(true)
    expect(shouldRetryApiRequest(reset, 'HEAD')).toBe(true)
    expect(shouldRetryApiRequest(reset, 'POST')).toBe(false)
    expect(shouldRetryApiRequest(reset, 'GET', true)).toBe(false)
    expect(shouldRetryApiRequest(new Error('timed out'), 'GET')).toBe(false)
  })

  it('bounds and removes controls from non-reset details', () => {
    const failure = apiIpcFailure(new Error(`bad\nrequest\u0000${'x'.repeat(600)}`))

    expect(failure.failure.detail).toHaveLength(512)
    expect(
      [...failure.failure.detail].some(character => {
        const codePoint = character.charCodeAt(0)

        return codePoint < 32 || codePoint === 127
      })
    ).toBe(false)
  })
})
