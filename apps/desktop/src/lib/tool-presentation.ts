import { SIGNAL_GREEN, SIGNAL_PENDING, SIGNAL_RED, SIGNAL_WARNING } from './ae-glyphs'

export const MODEL_VISIBLE_TOOL_RESULT_KEY = '__hermes_model_visible_result'

export interface McpToolIdentity {
  server: string
  tool: string
}

export interface McpUguiDocument {
  actions?: unknown[]
  header: unknown[]
  hostEffect?: unknown
  id: string
  provenance?: Record<string, unknown>
  receipt?: Record<string, unknown>
  schema: string
  sections: unknown[]
  state?: string
  type: 'document' | 'lucid'
  verb?: string
}

export function mcpToolIdentity(name: string): McpToolIdentity | null {
  const [transport, server, ...toolParts] = name.split('__')

  if (transport !== 'mcp' || !server || toolParts.length === 0) {
    return null
  }

  const tool = toolParts.join('__').replace(/_/g, ' ').trim()

  return tool ? { server, tool } : null
}

export function mcpToolTitle(name: string): string | null {
  const identity = mcpToolIdentity(name)

  return identity ? `${identity.server} ${identity.tool}` : null
}

export function modelVisibleToolResult(result: unknown): unknown {
  if (!result || typeof result !== 'object' || Array.isArray(result)) {
    return result
  }

  const record = result as Record<string, unknown>

  if (Object.hasOwn(record, MODEL_VISIBLE_TOOL_RESULT_KEY)) {
    return record[MODEL_VISIBLE_TOOL_RESULT_KEY]
  }

  const { duration_s: _duration, ...visible } = record

  return visible
}

function presentationToolResult(result: unknown): Record<string, unknown> | null {
  const channel = record(result)

  if (channel?.schema !== 'hermes-tool-result-channels/1') {
    return null
  }

  return record(channel.presentation)
}

function terminalLucidInvocations(args: unknown): string[] {
  const command = record(args)?.command

  if (typeof command !== 'string') {
    return []
  }

  return command
    .split(/&&|\|\||;|\n/)
    .map(segment => segment.trim())
    .filter(invocation => /^(?:env\s+)?(?:[A-Za-z_][A-Za-z0-9_]*=\S+\s+)*(?:\S+\/)?lucid(?=\s|$)/i.test(invocation))
}

export function terminalRunsLucid(args: unknown): boolean {
  return terminalLucidInvocations(args).length > 0
}

export function isTerminalTool(name: string): boolean {
  return name === 'terminal' || name.endsWith('.terminal') || name.endsWith('__terminal')
}

export function terminalRequestsUgui(args: unknown): boolean {
  return terminalLucidInvocations(args).some(
    invocation =>
      /(?:^|\s)--modality(?:=|\s+)ugui(?=\s|$)/i.test(invocation) || /(?:^|\s)--help=ugui(?=\s|$)/i.test(invocation)
  )
}

function record(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return value as Record<string, unknown>
  }

  if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value)

      return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? (parsed as Record<string, unknown>) : null
    } catch {
      return null
    }
  }

  return null
}

export function extractMcpGestalt(result: unknown): string | null {
  const channel = record(result)
  const presentation = presentationToolResult(result)
  const visibleValue =
    channel?.schema === 'hermes-tool-result-channels/1' && typeof channel.model === 'string'
      ? channel.model
      : modelVisibleToolResult(result)
  const visible = record(visibleValue)
  const candidates: unknown[] = [
    visibleValue,
    visible?.result,
    visible?.output,
    visible?.error,
    presentation?.result,
    presentation?.output
  ]

  // Transport candidate selection only. The Rust projector owns grammar and
  // refusal; a second parser here rejected valid CLI/semantic continuations.
  const candidateText = (value: string): boolean =>
    value.length <= 1_048_576 && !/[\r\n\0]/.test(value) &&
    [SIGNAL_GREEN, SIGNAL_PENDING, SIGNAL_RED, SIGNAL_WARNING].some(
      signal => value === signal || value.startsWith(`${signal} `)
    )

  for (const candidate of candidates) {
    if (typeof candidate === 'string' && candidateText(candidate)) {
      return candidate
    }

    const content = record(candidate)?.content

    if (!Array.isArray(content)) {
      continue
    }

    for (const item of content) {
      const row = record(item)
      const value = typeof row?.text === 'string' ? row.text : null

      if (value && candidateText(value)) {
        return value
      }
    }
  }

  return null
}

export function extractMcpUguiDocument(result: unknown): McpUguiDocument | null {
  const raw = record(result)
  const visible = record(modelVisibleToolResult(result))
  const presentation = presentationToolResult(result)

  const candidates = [
    record(presentation?.structuredContent),
    record(presentation?.result),
    record(presentation?.output),
    presentation,
    record(raw?.structuredContent),
    record(raw?.result),
    record(raw?.output),
    raw,
    record(visible?.structuredContent),
    record(visible?.result),
    record(visible?.output),
    visible
  ]

  for (const candidate of candidates) {
    if (
      !candidate ||
      typeof candidate.schema !== 'string' ||
      !/^[a-z0-9][a-z0-9._/-]{0,127}$/i.test(candidate.schema) ||
      typeof candidate.id !== 'string' ||
      !candidate.id ||
      (candidate.type !== 'lucid' && candidate.type !== 'document') ||
      !Array.isArray(candidate.header) ||
      candidate.header.length > 16 ||
      !Array.isArray(candidate.sections) ||
      candidate.sections.length > 32 ||
      (candidate.actions !== undefined && (!Array.isArray(candidate.actions) || candidate.actions.length > 32))
    ) {
      continue
    }

    return candidate as unknown as McpUguiDocument
  }

  return null
}

export function extractToolUguiDocument(toolName: string, args: unknown, result: unknown): McpUguiDocument | null {
  if (!mcpToolIdentity(toolName) && !(isTerminalTool(toolName) && terminalRequestsUgui(args))) {
    return null
  }

  return extractMcpUguiDocument(result)
}
