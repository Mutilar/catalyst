import type { McpServerSummary } from '@/types/hermes'

export type LucidStatusSignal = 'green' | 'hourglass' | 'red' | 'warning'

export interface LucidMcpStatus {
  connection: string
  error: string | null
  failures: number
  glyph: '⚠️' | '⏳' | '🔴' | '🟢'
  health: string
  signal: LucidStatusSignal
  tools: number
  transport: string
}

const STATUS: Record<LucidStatusSignal, Pick<LucidMcpStatus, 'glyph' | 'signal'>> = {
  green: { glyph: '🟢', signal: 'green' },
  hourglass: { glyph: '⏳', signal: 'hourglass' },
  red: { glyph: '🔴', signal: 'red' },
  warning: { glyph: '⚠️', signal: 'warning' }
}

export function lucidMcpGestalt(status: LucidMcpStatus): string {
  const state = {
    green: 'healthy',
    hourglass: 'pending',
    red: 'failed',
    warning: 'degraded'
  }[status.signal]
  const lines: Array<string | null> = [
    `${status.glyph} · 🧠 · ⚡ SHOW · 🎯 MCP · 🎛️ ${state.toUpperCase()}`,
    `◆ MCP Connection=${status.connection} · Health=${status.health} · Transport=${status.transport.toUpperCase()} · Tools=${status.tools} · Failures=${status.failures} · Startup=Automatic`
  ]
  const error = status.error?.replace(/[\r\n\0]+/g, ' ').trim().slice(0, 512)

  lines.push(
    error
      ? `🔎 Code=lucid-health-error · Detail=${error}`
      : null
  )
  if (status.connection.startsWith('Connected') && status.tools > 0) {
    lines.push('➡️ {"arguments":{},"label":"Open LUCID capabilities","verb":"get"}')
  }

  return lines.filter((line): line is string => Boolean(line)).join('\n')
}

export function lucidMcpTooltip(status: LucidMcpStatus): string {
  return lucidMcpGestalt(status)
}

export function deriveLucidMcpStatus(
  servers: McpServerSummary[] | undefined,
  options: { error?: unknown; loading?: boolean } = {}
): LucidMcpStatus {
  if (options.error) {
    return {
      ...STATUS.red,
      connection: 'Status unavailable',
      error: options.error instanceof Error ? options.error.message : String(options.error),
      failures: 0,
      health: 'Unobservable',
      tools: 0,
      transport: 'unknown'
    }
  }

  if (options.loading || !servers) {
    return {
      ...STATUS.hourglass,
      connection: 'Discovering',
      error: null,
      failures: 0,
      health: 'Startup observation in progress',
      tools: 0,
      transport: 'unknown'
    }
  }

  const lucid = servers.find(server => server.name.toLowerCase() === 'lucid')

  if (!lucid) {
    return {
      ...STATUS.red,
      connection: 'Not configured',
      error: 'The required LUCID MCP server is absent from this profile.',
      failures: 0,
      health: 'Unavailable',
      tools: 0,
      transport: 'unknown'
    }
  }

  const base = {
    error: lucid.health_error ?? lucid.connection_error,
    failures: lucid.consecutive_failures,
    tools: lucid.discovered_tools,
    transport: lucid.transport
  }

  if (!lucid.enabled || lucid.runtime_status === 'disabled') {
    return {
      ...STATUS.red,
      ...base,
      connection: 'Disabled',
      health: 'Unavailable'
    }
  }

  if (lucid.runtime_status === 'connecting') {
    return {
      ...STATUS.hourglass,
      ...base,
      connection: 'Connecting',
      health: 'Handshake in progress'
    }
  }

  if (lucid.runtime_status === 'failed') {
    return {
      ...STATUS.red,
      ...base,
      connection: 'Failed',
      health: 'Unhealthy'
    }
  }

  if (lucid.connected && lucid.runtime_status === 'connected') {
    if (lucid.health_status === 'unhealthy' || lucid.health_status === 'unavailable') {
      return {
        ...STATUS.red,
        ...base,
        connection: 'Connected, unhealthy',
        health: lucid.health_status === 'unhealthy' ? 'Unhealthy' : 'Unobservable'
      }
    }

    if (lucid.health_status === 'degraded') {
      return {
        ...STATUS.warning,
        ...base,
        connection: 'Connected, degraded',
        health: 'Degraded'
      }
    }

    if (lucid.health_status === 'pending') {
      return {
        ...STATUS.hourglass,
        ...base,
        connection: 'Connected, health pending',
        health: 'Awaiting successful keepalive or tool call'
      }
    }

    if (lucid.discovered_tools <= 0) {
      return {
        ...STATUS.red,
        ...base,
        connection: 'Connected without tools',
        health: 'Capability evidence missing'
      }
    }

    return {
      ...STATUS.green,
      ...base,
      connection: 'Connected',
      error: null,
      health: 'Healthy'
    }
  }

  return {
    ...STATUS.warning,
    ...base,
    connection: 'Configured, not connected',
    health: 'Startup connection absent'
  }
}
