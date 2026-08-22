import { describe, expect, it } from 'vitest'

import {
  extractMcpGestalt,
  extractMcpUguiDocument,
  extractToolUguiDocument,
  mcpToolIdentity,
  mcpToolTitle,
  MODEL_VISIBLE_TOOL_RESULT_KEY,
  modelVisibleToolResult,
  terminalRunsLucid,
  terminalRequestsUgui
} from './tool-presentation'

const document = {
  schema: 'lucid-ugui-response/1',
  id: 'lucid.response',
  type: 'lucid',
  verb: 'morph',
  state: 'complete',
  header: [{ id: 'title', type: 'text', body: 'LUCID morph' }],
  sections: [{ id: 'status', type: 'status', signal: '🟢', body: 'Complete' }],
  actions: []
}

describe('MCP presentation identity', () => {
  it('removes transport syntax for every MCP namespace', () => {
    expect(mcpToolIdentity('mcp__LUCID__morph')).toEqual({ server: 'LUCID', tool: 'morph' })
    expect(mcpToolTitle('mcp__FILES__read_document')).toBe('FILES read document')
    expect(mcpToolTitle('terminal')).toBeNull()
  })
})

describe('model-visible MCP result', () => {
  it('uses the exact retained payload instead of Hermes timing metadata', () => {
    const visible = { error: 'malformed' }
    const result = { duration_s: 1.8, error: 'malformed', [MODEL_VISIBLE_TOOL_RESULT_KEY]: visible }

    expect(modelVisibleToolResult(result)).toBe(visible)
  })
})

describe('UGUI extraction', () => {
  it('separates full presentation UGUI from the model-visible Gestalt sidecar', () => {
    const gestalt = '🟢 LUCID · get · onboarding · ready'
    const result = {
      [MODEL_VISIBLE_TOOL_RESULT_KEY]: gestalt,
      result: gestalt,
      structuredContent: document
    }

    expect(modelVisibleToolResult(result)).toBe(gestalt)
    expect(extractMcpUguiDocument(result)).toEqual(document)
  })

  it('admits a bounded canonical LUCID UGUI document', () => {
    const result = {
      duration_s: 0.4,
      [MODEL_VISIBLE_TOOL_RESULT_KEY]: { content: [], isError: false, structuredContent: document }
    }

    expect(extractMcpUguiDocument(result)).toEqual(document)
  })

  it('renders structured UGUI for MCP domain refusals marked isError', () => {
    const refusal = { ...document, state: 'bootstrap-decision-required' }
    const result = {
      [MODEL_VISIBLE_TOOL_RESULT_KEY]: {
        content: [{ type: 'text', text: 'fallback GESTALT' }],
        isError: true,
        structuredContent: refusal
      }
    }

    expect(extractToolUguiDocument('mcp__LUCID__set', {}, result)).toEqual(refusal)
  })

  it('refuses arbitrary structured content and oversized documents', () => {
    expect(
      extractMcpUguiDocument({
        structuredContent: { schema: 'unknown/1', id: 'opaque', type: 'data', payload: {} }
      })
    ).toBeNull()
    expect(
      extractMcpUguiDocument({
        structuredContent: { ...document, sections: Array.from({ length: 33 }, (_, index) => ({ id: index })) }
      })
    ).toBeNull()
  })

  it('admits UGUI documents independently of MCP server and schema prefix', () => {
    const generic = { ...document, schema: 'acme-ugui-document/1', type: 'document' }

    expect(extractMcpUguiDocument({ structuredContent: generic })).toEqual(generic)
    expect(extractMcpUguiDocument({ result: generic })).toEqual(generic)
    expect(extractMcpUguiDocument(generic)).toEqual(generic)
  })

  it('admits an exact UGUI document emitted as terminal stdout', () => {
    expect(extractMcpUguiDocument({ output: JSON.stringify(document), exit_code: 0 })).toEqual(document)
  })
})

describe('Gestalt extraction', () => {
  it('extracts one bounded canonical Gestalt without interpreting its fields', () => {
    const gestalt = [
      '⚠️ LUCID · get · logs · stale',
      'Runtime logs Source=catalyst',
      'Runtime logs Freshness=stale'
    ].join('\n')
    const result = {
      [MODEL_VISIBLE_TOOL_RESULT_KEY]: {
        content: [{ type: 'text', text: gestalt }],
        isError: false
      }
    }

    expect(extractMcpGestalt(result)).toBe(gestalt)
  })

  it('refuses arbitrary prose while leaving bounds to the shared projector', () => {
    expect(extractMcpGestalt({ content: [{ type: 'text', text: 'ordinary prose' }] })).toBeNull()
    const oversized = `🟢 LUCID · get · logs · fresh\n${'x'.repeat(2_048)}`
    expect(extractMcpGestalt(oversized)).toBe(oversized)
  })

  it('extracts the existing CLI pulse header without parsing its semantics', () => {
    const pulse = '🔴 QUINE.md · root · current\n🟢 GREEN'

    expect(extractMcpGestalt({ output: pulse, exit_code: 0 })).toBe(pulse)
  })

  it('extracts canonical CLI help nested in terminal output', () => {
    const help = [
      '🟢 LUCID · get · help · ready',
      'Read exact registered evidence.',
      'CALL lucid get [typed arguments]'
    ].join('\n')

    expect(terminalRunsLucid({ command: 'lucid get --help' })).toBe(true)
    expect(extractMcpGestalt({ output: help, exit_code: 0 })).toBe(help)
  })
})

describe('terminal UGUI selection', () => {
  it('routes every direct lucid CLI invocation to the shared projector', () => {
    expect(terminalRunsLucid({ command: 'lucid show pulse' })).toBe(true)
    expect(terminalRunsLucid({ command: '/repo/bin/lucid get --args \'{"path":"gates"}\'' })).toBe(true)
    expect(terminalRunsLucid({ command: 'echo lucid show pulse' })).toBe(false)
  })

  it('recognizes direct LUCID UGUI commands and stable launcher paths', () => {
    expect(terminalRequestsUgui({ command: "LUCID show pulse --modality ugui" })).toBe(
      true
    )
    expect(
      terminalRequestsUgui({
        command: '/repo/run/target/toolchains/butler/current/bin/LUCID show --help --modality=ugui'
      })
    ).toBe(true)
    expect(terminalRequestsUgui({ command: 'LUCID --help=ugui' })).toBe(true)
  })

  it('does not reinterpret ordinary terminal JSON or merely mentioned syntax', () => {
    expect(terminalRequestsUgui({ command: 'printf \'%s\' \'{"schema":"fake"}\'' })).toBe(false)
    expect(terminalRequestsUgui({ command: 'echo LUCID show --modality ugui' })).toBe(false)
    expect(terminalRequestsUgui({ command: 'LUCID show --modality envelope' })).toBe(false)
  })

  it('routes selected LUCID terminal stdout through the UGUI admission boundary', () => {
    const result = { output: JSON.stringify(document), exit_code: 0 }

    expect(extractToolUguiDocument('terminal', { command: 'LUCID show --help --modality ugui' }, result)).toEqual(
      document
    )
    expect(extractToolUguiDocument('terminal', { command: 'echo ordinary' }, result)).toBeNull()
  })
})
