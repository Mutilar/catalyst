import { describe, expect, it } from 'vitest'

import type { McpServerSummary } from '@/types/hermes'

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
    expect(deriveLucidMcpStatus([lucid({ connected: false, enabled: false, runtime_status: 'disabled' })]).glyph).toBe('🔴')
    expect(deriveLucidMcpStatus([lucid({ discovered_tools: 0 })]).glyph).toBe('🔴')
  })

  it('uses hourglass only for a live observation or connection attempt', () => {
    expect(deriveLucidMcpStatus(undefined, { loading: true }).signal).toBe('hourglass')
    expect(deriveLucidMcpStatus([lucid({ connected: false, runtime_status: 'connecting' })]).signal).toBe('hourglass')
  })

  it('lets runtime health dominate a successful transport handshake', () => {
    expect(
      deriveLucidMcpStatus([
        lucid({ consecutive_failures: 3, health_error: 'validated domain-result projection failed', health_status: 'unhealthy' })
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
    expect(gestalt.split('\n')).toEqual([
      '🔴 LUCID · show · mcp · failed',
      'MCP Connection=Connected, unhealthy · Health=Unhealthy · Transport=STDIO · Tools=7 · Failures=3 · Startup=Automatic',
      '🔎 Code=lucid-health-error · Detail=projection failed',
      '➡️ {"arguments":{},"label":"Open LUCID capabilities","verb":"get"}'
    ])
    expect(gestalt).not.toContain('show · health')
  })

  it('emits capabilities as a typed next action only with connected tool evidence', () => {
    const available = lucidMcpGestalt(deriveLucidMcpStatus([lucid()]))
    const unavailable = lucidMcpGestalt(
      deriveLucidMcpStatus([lucid({ connected: false, runtime_status: 'connecting' })])
    )
    const toolLess = lucidMcpGestalt(deriveLucidMcpStatus([lucid({ discovered_tools: 0 })]))

    expect(available).toContain(
      '➡️ {"arguments":{},"label":"Open LUCID capabilities","verb":"get"}'
    )
    expect(unavailable).not.toContain('➡️ ')
    expect(toolLess).not.toContain('➡️ ')
  })

  it('sanitizes error text before admitting it to GESTALT', () => {
    const gestalt = lucidMcpGestalt(
      deriveLucidMcpStatus([
        lucid({ health_error: 'line one\nline two\0', health_status: 'unhealthy' })
      ])
    )

    expect(gestalt).toContain('🔎 Code=lucid-health-error · Detail=line one line two')
    expect(gestalt).not.toContain('\0')
  })
})
