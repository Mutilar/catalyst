import { describe, expect, it } from 'vitest'

import { IDENTITY_RUN, SIGNAL_GREEN, SIGNAL_PENDING, SIGNAL_RED, SIGNAL_WARNING } from '@/lib/ae-glyphs'
import type { McpServerSummary } from '@/types/hermes'

import gestaltContract from '../../../../../envelope/GESTALT.json'
import glyphRegistry from '../../../../../quine/canon/GLYPH.json'
import conformanceData from '../../../../../quine/tests/fixtures/gestalt-conformance.json'

import { canonicalGestaltStream, type GestaltSemanticStream, parseGestaltStream } from './lucid-gestalt'
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
    expect(deriveLucidMcpStatus([lucid()]).glyph).toBe(SIGNAL_GREEN)
    expect(deriveLucidMcpStatus([lucid({ connected: false, runtime_status: 'connecting' })]).glyph).toBe(SIGNAL_PENDING)
    expect(deriveLucidMcpStatus([lucid({ connected: false, runtime_status: 'configured' })]).glyph).toBe(SIGNAL_WARNING)
    expect(deriveLucidMcpStatus([lucid({ connected: false, runtime_status: 'failed' })]).glyph).toBe(SIGNAL_RED)
  })

  it('treats missing LUCID, disabled LUCID, and capability-empty connections as red', () => {
    expect(deriveLucidMcpStatus([]).glyph).toBe(SIGNAL_RED)
    expect(deriveLucidMcpStatus([lucid({ connected: false, enabled: false, runtime_status: 'disabled' })]).glyph).toBe(
      SIGNAL_RED
    )
    expect(deriveLucidMcpStatus([lucid({ discovered_tools: 0 })]).glyph).toBe(SIGNAL_RED)
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
    ).toBe(SIGNAL_RED)
    expect(deriveLucidMcpStatus([lucid({ consecutive_failures: 1, health_status: 'degraded' })]).glyph).toBe(
      SIGNAL_WARNING
    )
    expect(deriveLucidMcpStatus([lucid({ health_status: 'pending' })]).glyph).toBe(SIGNAL_PENDING)
  })

  it('builds one canonical GESTALT for the tooltip and UGUI modal', () => {
    const status = deriveLucidMcpStatus([
      lucid({ consecutive_failures: 3, health_error: 'projection failed', health_status: 'unhealthy' })
    ])

    const gestalt = lucidMcpGestalt(status)
    const tooltip = lucidMcpTooltip(status)

    expect(tooltip).toBe(gestalt)
    const stream = parseGestaltStream(gestalt)
    expect([stream.signal, stream.verb, stream.noun, stream.argument]).toEqual([SIGNAL_RED, 'show', 'mcp', 'FAILED'])
    expect(stream.data).toEqual([
      'MCP Connection=Connected, unhealthy, Health=Unhealthy, Transport=STDIO, Tools=7, Failures=3, Startup=Automatic'
    ])
    expect(stream.evidence).toEqual(['Code=lucid-health-error, Detail=projection failed'])
    expect(stream.actions).toEqual([{ verb: 'get', arguments: [], label: 'Open LUCID capabilities' }])
  })

  it('emits capabilities as a typed next action only with connected tool evidence', () => {
    const available = lucidMcpGestalt(deriveLucidMcpStatus([lucid()]))

    const unavailable = lucidMcpGestalt(
      deriveLucidMcpStatus([lucid({ connected: false, runtime_status: 'connecting' })])
    )

    const toolLess = lucidMcpGestalt(deriveLucidMcpStatus([lucid({ discovered_tools: 0 })]))

    expect(parseGestaltStream(available).actions).toEqual([
      { verb: 'get', arguments: [], label: 'Open LUCID capabilities' }
    ])
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
      signal: SIGNAL_PENDING,
      service: IDENTITY_RUN,
      timing: [`${SIGNAL_RED} RTT [################] 200% T+5.0`]
    })

    expect(parseGestaltStream(gestalt).timing).toEqual([`${SIGNAL_RED} RTT [################] 200% T+5.0`])
    expect(gestalt).not.toContain('SERVICE')
    expect(gestalt).not.toContain('TIMING')
  })
})

const conformance = conformanceData as {
  positive: {
    id: string
    canonical: string
    stream: GestaltSemanticStream
    render?: GestaltSemanticStream
    source?: string
  }[]
  negative: { id: string; source?: string; stream?: GestaltSemanticStream }[]
}

function conformanceFields(stream: GestaltSemanticStream) {
  const continuations = (stream.continuations ?? []).map(value =>
    typeof value === 'string' ? { kind: 'service', value } : value
  )

  expect(stream.intents).toEqual(continuations.filter(entry => entry.kind === 'intent').map(entry => entry.value))
  expect(stream.cli).toEqual(continuations.filter(entry => entry.kind === 'cli').map(entry => entry.value))

  return {
    signal: stream.signal,
    service: stream.service ?? null,
    verb: stream.verb ?? null,
    noun: stream.noun ?? null,
    arguments: stream.arguments ?? [],
    evidence: stream.evidence ?? [],
    data: stream.data ?? [],
    timing: stream.timing ?? [],
    continuations,
    actions: (stream.actions ?? []).map(action => ({
      verb: action.verb,
      noun: action.noun ?? null,
      arguments: action.arguments ?? [],
      label: action.label ?? null
    }))
  }
}

describe('shared Rust/JS/Python GESTALT conformance', () => {
  it.each(Object.keys(glyphRegistry.bindings.retired_tokens))('rejects retired service marker %s', retired => {
    const separator = gestaltContract.segments.separator
    const action = gestaltContract.segments.glyphs.action

    expect(() => parseGestaltStream([SIGNAL_GREEN, retired].join(separator))).toThrow()
    expect(() => parseGestaltStream([SIGNAL_GREEN, `${action} ${retired}`].join(separator))).toThrow()
    expect(() => canonicalGestaltStream({ signal: SIGNAL_GREEN, service: retired })).toThrow()
    expect(() => canonicalGestaltStream({ signal: SIGNAL_GREEN, continuations: [retired] })).toThrow()

    const historical = `Historical \`${retired}\``
    const rendered = canonicalGestaltStream({ signal: SIGNAL_GREEN, data: [historical] })

    expect(parseGestaltStream(rendered).data).toEqual([historical])
  })

  it.each(conformance.positive)('round trips $id', testCase => {
    expect(canonicalGestaltStream(testCase.render ?? testCase.stream)).toBe(testCase.canonical)
    const parsed = parseGestaltStream(testCase.source ?? testCase.canonical)
    expect(conformanceFields(parsed)).toEqual(testCase.stream)
    expect(canonicalGestaltStream(parsed)).toBe(testCase.canonical)
  })

  it.each(conformance.negative)('refuses $id', testCase => {
    if (testCase.source !== undefined) {
      expect(() => parseGestaltStream(testCase.source!)).toThrow()
    }

    if (testCase.stream !== undefined) {
      expect(() => canonicalGestaltStream(testCase.stream!)).toThrow()
    }
  })

  it('preserves singular argument compatibility and rejects conflicting plural arguments', () => {
    const literal = `TERM \`MiXeD${gestaltContract.segments.separator}bytes\``

    const rendered = canonicalGestaltStream({
      signal: SIGNAL_GREEN,
      verb: 'get',
      noun: 'search',
      argument: 'first',
      actions: [{ verb: 'get', noun: 'search', argument: literal }]
    })

    const parsed = parseGestaltStream(rendered)
    expect(parsed.arguments).toEqual(['FIRST'])
    expect(parsed.argument).toBe('FIRST')
    expect(parsed.actions?.[0].argument).toBe(literal)
    expect(canonicalGestaltStream(parsed)).toBe(rendered)

    for (const arguments_ of [['SECOND'], ['FIRST', 'SECOND']]) {
      expect(() =>
        canonicalGestaltStream({
          signal: SIGNAL_GREEN,
          verb: 'get',
          noun: 'search',
          argument: 'FIRST',
          arguments: arguments_
        })
      ).toThrow('argument sources conflict')
      expect(() =>
        canonicalGestaltStream({
          signal: SIGNAL_GREEN,
          actions: [{ verb: 'get', noun: 'search', argument: 'FIRST', arguments: arguments_ }]
        })
      ).toThrow('argument sources conflict')
    }
  })

  it('supports legacy intent and CLI shorthand alongside identity-free streams', () => {
    const intent = `Inspect MiXeD${gestaltContract.segments.separator}bytes`
    const command = `printf 'MiXeD${gestaltContract.segments.separator}bytes'`

    const rendered = canonicalGestaltStream({
      signal: SIGNAL_GREEN,
      withoutIdentity: true,
      intents: [intent],
      cli: [command]
    })

    const parsed = parseGestaltStream(rendered)
    expect(parsed.service).toBeNull()
    expect(parsed.continuations).toEqual([
      { kind: 'intent', value: intent },
      { kind: 'cli', value: command }
    ])
    expect(parsed.intents).toEqual([intent])
    expect(parsed.cli).toEqual([command])
    expect(canonicalGestaltStream(parsed)).toBe(rendered)

    for (const field of ['intents', 'cli']) {
      expect(() => canonicalGestaltStream({ ...parsed, [field]: ['Changed'] })).toThrow('continuation sources conflict')
    }

    expect(() =>
      canonicalGestaltStream({
        signal: SIGNAL_GREEN,
        service: IDENTITY_RUN,
        withoutIdentity: true
      })
    ).toThrow('service conflicts')
  })
})
