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
      '🔴 LUCID · show · mcp-health · failed',
      'MCP Connection=Connected, unhealthy',
      'MCP Health=Unhealthy',
      'MCP Transport=STDIO',
      'MCP Tools=7',
      'MCP Failures=3',
      '🔎 Code=mcp-health-error · Detail=projection failed'
    ])
  })

  it('sanitizes error text before admitting it to GESTALT', () => {
    const gestalt = lucidMcpGestalt(
      deriveLucidMcpStatus([
        lucid({ health_error: 'line one\nline two\0', health_status: 'unhealthy' })
      ])
    )

    expect(gestalt).toContain('🔎 Code=mcp-health-error · Detail=line one line two')
    expect(gestalt).not.toContain('\0')
  })
})
