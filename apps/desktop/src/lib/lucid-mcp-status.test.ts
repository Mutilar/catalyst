import { describe, expect, it } from 'vitest'

import type { McpServerSummary } from '@/types/hermes'

import { deriveLucidMcpStatus, lucidMcpTooltip } from './lucid-mcp-status'

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

  it('builds the titlebar tooltip as the same plain-text label used by other controls', () => {
    const tooltip = lucidMcpTooltip(
      deriveLucidMcpStatus([
        lucid({ consecutive_failures: 3, health_error: 'projection failed', health_status: 'unhealthy' })
      ])
    )

    expect(typeof tooltip).toBe('string')
    expect(tooltip).toContain('🔴 LUCID MCP')
    expect(tooltip).toContain('Health: Unhealthy')
    expect(tooltip).toContain('Transport: STDIO')
    expect(tooltip).toContain('Discovered tools: 7')
    expect(tooltip).toContain('Consecutive failures: 3')
    expect(tooltip).toContain('Cause: projection failed')
    expect(tooltip).toContain('Capabilities → MCP')
  })
})
