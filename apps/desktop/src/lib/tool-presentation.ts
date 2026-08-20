export const MODEL_VISIBLE_TOOL_RESULT_KEY = '__hermes_model_visible_result'

export interface McpToolIdentity {
  server: string
  tool: string
}

export interface McpUguiDocument {
  actions?: unknown[]
  header: unknown[]
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

export function terminalRequestsUgui(args: unknown): boolean {
  const command = record(args)?.command

  if (typeof command !== 'string') {
    return false
  }

  return command.split(/&&|\|\||;|\n/).some(segment => {
    const invocation = segment.trim()

    if (!/^(?:env\s+)?(?:[A-Za-z_][A-Za-z0-9_]*=\S+\s+)*(?:\S+\/)?lucid(?=\s|$)/i.test(invocation)) {
      return false
    }

    return (
      /(?:^|\s)--modality(?:=|\s+)ugui(?=\s|$)/i.test(invocation) ||
      /(?:^|\s)--help=ugui(?=\s|$)/i.test(invocation)
    )
  })
}

function record(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return value as Record<string, unknown>
  }

  if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value)

      return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
        ? (parsed as Record<string, unknown>)
        : null
    } catch {
      return null
    }
  }

  return null
}

export function extractMcpUguiDocument(result: unknown): McpUguiDocument | null {
  const visible = record(modelVisibleToolResult(result))

  const candidates = [
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
  if (!mcpToolIdentity(toolName) && !(toolName === 'terminal' && terminalRequestsUgui(args))) {
    return null
  }

  return extractMcpUguiDocument(result)
}
