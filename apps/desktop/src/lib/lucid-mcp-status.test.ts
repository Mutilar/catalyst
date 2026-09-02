import { describe, expect, it } from 'vitest'

import type { McpServerSummary } from '@/types/hermes'

import { canonicalGestaltStream, parseGestaltStream } from './lucid-gestalt'
import { deriveLucidMcpStatus, lucidMcpGestalt, lucidMcpTooltip } from './lucid-mcp-status'

const lucid = (overrides: Partial<McpServerSummary> = {}): McpServerSummary => ({
  args: ['mcp'],
  command: 'butler',
  connected: true,
  connection_error: null,
  consecutive_failures: 0,
  discovered_tools: 7,
  enabled: true,
  name: 'LUCID',
  health_error: null,
  health_status: 'healthy',
  runtime_status: 'connected',
  runtime_tools: ['show', 'get', 'set', 'morph', 'dispatch', 'steer', 'cancel'],
  tools: null,
  transport: 'stdio',
  url: null,
  ...overrides
})

describe('LUCID MCP titlebar status', () => {
  it('projects every canonical signal deterministically', () => {
    expect(deriveLucidMcpStatus([lucid()]).glyph).toBe('🟢')
    expect(deriveLucidMcpStatus([lucid({ connected: false, runtime_status: 'connecting' })]).glyph).toBe('⏳')
    expect(deriveLucidMcpStatus([lucid({ connected: false, runtime_status: 'configured' })]).glyph).toBe('⚠️')
    expect(deriveLucidMcpStatus([lucid({ connected: false, runtime_status: 'failed' })]).glyph).toBe('🔴')
  })

  it('treats missing LUCID, disabled LUCID, and capability-empty connections as red', () => {
    expect(deriveLucidMcpStatus([]).glyph).toBe('🔴')
    expect(deriveLucidMcpStatus([lucid({ connected: false, enabled: false, runtime_status: 'disabled' })]).glyph).toBe(
      '🔴'
    )
    expect(deriveLucidMcpStatus([lucid({ discovered_tools: 0 })]).glyph).toBe('🔴')
  })

  it('uses hourglass only for a live observation or connection attempt', () => {
    expect(deriveLucidMcpStatus(undefined, { loading: true }).signal).toBe('hourglass')
    expect(deriveLucidMcpStatus([lucid({ connected: false, runtime_status: 'connecting' })]).signal).toBe('hourglass')
  })

  it('lets runtime health dominate a successful transport handshake', () => {
    expect(
      deriveLucidMcpStatus([
        lucid({
          consecutive_failures: 3,
          health_error: 'validated domain-result projection failed',
          health_status: 'unhealthy'
        })
      ]).glyph
    ).toBe('🔴')
    expect(deriveLucidMcpStatus([lucid({ consecutive_failures: 1, health_status: 'degraded' })]).glyph).toBe('⚠️')
    expect(deriveLucidMcpStatus([lucid({ health_status: 'pending' })]).glyph).toBe('⏳')
  })

  it('builds one canonical GESTALT for the tooltip and UGUI modal', () => {
    const status = deriveLucidMcpStatus([
      lucid({ consecutive_failures: 3, health_error: 'projection failed', health_status: 'unhealthy' })
    ])
    const gestalt = lucidMcpGestalt(status)
    const tooltip = lucidMcpTooltip(status)

    expect(tooltip).toBe(gestalt)
    const stream = parseGestaltStream(gestalt)
    expect([stream.signal, stream.verb, stream.noun, stream.argument]).toEqual(['🔴', 'show', 'mcp', 'FAILED'])
    expect(stream.data).toEqual([
      'MCP Connection=Connected, unhealthy, Health=Unhealthy, Transport=STDIO, Tools=7, Failures=3, Startup=Automatic'
    ])
    expect(stream.evidence).toEqual(['Code=lucid-health-error, Detail=projection failed'])
    expect(stream.actions).toEqual([{ verb: 'get', label: 'Open LUCID capabilities' }])
  })

  it('emits capabilities as a typed next action only with connected tool evidence', () => {
    const available = lucidMcpGestalt(deriveLucidMcpStatus([lucid()]))
    const unavailable = lucidMcpGestalt(
      deriveLucidMcpStatus([lucid({ connected: false, runtime_status: 'connecting' })])
    )
    const toolLess = lucidMcpGestalt(deriveLucidMcpStatus([lucid({ discovered_tools: 0 })]))

    expect(parseGestaltStream(available).actions).toEqual([{ verb: 'get', label: 'Open LUCID capabilities' }])
    expect(parseGestaltStream(unavailable).actions).toEqual([])
    expect(parseGestaltStream(toolLess).actions).toEqual([])
  })

  it('sanitizes error text before admitting it to GESTALT', () => {
    const gestalt = lucidMcpGestalt(
      deriveLucidMcpStatus([lucid({ health_error: 'line one\nline two\0', health_status: 'unhealthy' })])
    )

    expect(parseGestaltStream(gestalt).evidence).toEqual(['Code=lucid-health-error, Detail=line one line two'])
    expect(gestalt).not.toContain('\0')
  })

  it('round trips status-bearing timing without label syntax', () => {
    const gestalt = canonicalGestaltStream({
      signal: '⏳',
      service: '🔥',
      timing: ['🔴 RTT [################] 200% T+5.0']
    })

    expect(parseGestaltStream(gestalt).timing).toEqual(['🔴 RTT [################] 200% T+5.0'])
    expect(gestalt).not.toContain('SERVICE')
    expect(gestalt).not.toContain('TIMING')
  })
})
