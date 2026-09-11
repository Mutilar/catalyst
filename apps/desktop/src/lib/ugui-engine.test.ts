import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'

import { describe, expect, it, vi } from 'vitest'

import { DELIMITER_SEGMENT, RELATION_ACTION, SIGNAL_GREEN } from './ae-glyphs'
import { canonicalGestaltStream } from './lucid-gestalt'
import { initializeUguiModule, parseConversationProjection, resolveUguiModuleUrls, resolveUguiWasmUrl } from './ugui-engine'

describe('conversation transport diagnostics', () => {
  const source = 'PRIVATE conversation source'

  const projection = () => ({
    schema: 'ugui-conversation-text/1', authority: 'presentation-only', source,
    documents: [{
      schema: 'lucid-ugui-response/1', type: 'document', id: 'conversation.text.0',
      authority: 'presentation-only', header: [], sections: [], actions: [],
      source, revision: 'revision', streamState: 'complete'
    }]
  })

  const parse = (value: unknown) => parseConversationProjection(JSON.stringify(value), source)

  it('admits one canonical envelope without rewriting source or documents', () => {
    const value = projection()
    expect(parse(value)).toEqual(value)
  })

  it.each([null, [], 'text', 42])('diagnoses a non-object envelope: %j', value => {
    expect(() => parse(value)).toThrow('conversation-projector-shape-invalid: / expected=object')
  })

  it('does not leak malformed JSON or arbitrary refusal text', () => {
    expect(() => parseConversationProjection(`{${source}`, source)).toThrow('conversation-projector-json-invalid: / expected=JSON object')
    expect(() => parse({ schema: 'ugui-conversation-text-error/1', code: source })).toThrow('conversation-projector-refused: /code unrecognized-refusal')
    expect(() => parse({ schema: 'ugui-conversation-text-error/1', code: 'conversation-text-byte-bound' })).toThrow('conversation-projector-refused: /code conversation-text-byte-bound')
  })

  it('distinguishes schema drift from obsolete payload shape without a fallback', () => {
    expect(() => parse({ ...projection(), schema: 'unsupported/1' })).toThrow('expected=ugui-conversation-text/1 observed=unsupported/1')
    expect(() => parse({ ...projection(), documents: undefined, blocks: [] })).toThrow('conversation-projector-shape-invalid: /documents expected=array')
  })

  it.each(['header', 'sections', 'actions'] as const)('identifies the invalid %s region and document index', region => {
    const value = projection()
    expect(() => parse({ ...value, documents: [value.documents[0], { ...value.documents[0], [region]: null }] })).toThrow(`conversation-projector-region-invalid: /documents/1/${region} expected=array`)
  })

  it('reports bounds without dumping document content', () => {
    const value = projection()
    expect(() => parse({ ...value, documents: [{ ...value.documents[0], sections: Array(33).fill(source) }] })).toThrow('conversation-projector-region-bound: /documents/0/sections maximum=32 observed=33')
  })

  it('identifies authority and metadata failures', () => {
    const value = projection()
    expect(() => parse({ ...value, authority: 'tool' })).toThrow('/authority expected=presentation-only')
    expect(() => parse({ ...value, documents: [null] })).toThrow('/documents/0 expected=object')
    expect(() => parse({ ...value, documents: [{ ...value.documents[0], authority: 'tool' }] })).toThrow('/documents/0/authority expected=presentation-only')
    expect(() => parse({ ...value, documents: [{ ...value.documents[0], revision: null }] })).toThrow('/documents/0/revision expected=string')
    expect(() => parse({ ...value, documents: [{ ...value.documents[0], streamState: 'unknown' }] })).toThrow('/documents/0/streamState expected=pending or complete')
  })

  it('refuses source substitution and lost or reordered source fragments', () => {
    const value = projection()
    expect(() => parse({ ...value, source: 'different' })).toThrow('/source expected=exact request source')
    expect(() => parse({ ...value, documents: [{ ...value.documents[0], source: 'different' }] })).toThrow('/documents expected=ordered lossless source partition')
    expect(parseConversationProjection(JSON.stringify({ ...value, source: ' \n', documents: [] }), ' \n').documents).toEqual([])
  })
})

describe('UGUI WASM module resolution', () => {
  it('projects through the actual generated conversation ABI, not a mocked document', async () => {
    const module = await import('../../public/wasm/ugui_gestalt_wasm.js')
    const bytes = await readFile(resolve('public/wasm/ugui_gestalt_wasm_bg.wasm'))
    await module.default({ module_or_path: new Uint8Array(bytes).buffer })
    const source = `${canonicalGestaltStream({ signal: SIGNAL_GREEN, data: ['First paragraph'] })}\n\nSecond paragraph`
    const pending = JSON.parse(module.ugui_project_conversation_text(source, true))
    const complete = JSON.parse(module.ugui_project_conversation_text(source, false))
    expect(pending.schema).toBe('ugui-conversation-text/1')
    expect(pending.authority).toBe('presentation-only')
    expect(pending.source).toBe(source)
    expect(pending.documents).toHaveLength(2)
    expect(pending.documents[0].schema).toBe('lucid-ugui-response/1')
    expect(pending.documents[0].actions).toEqual([])
    expect(pending.documents[0].hostEffect).toBeUndefined()
    expect(pending.documents[1].streamState).toBe('pending')
    expect(complete.documents[1].streamState).toBe('complete')
    expect(complete.documents[0]).toEqual(pending.documents[0])
    const cyoa = `${SIGNAL_GREEN}${DELIMITER_SEGMENT}${RELATION_ACTION} "Inspect"`
    const choice = JSON.parse(module.ugui_project_conversation_text(cyoa, false))
    expect(choice.documents[0].sections).toEqual([])
    expect(choice.documents[0].actions).toContainEqual(expect.objectContaining({
      type: 'button', action: 'conversation.submit', label: 'Inspect', value: 'Inspect', disabled: false
    }))
    const adjacent = ['First', 'Second', 'Third'].map(value => canonicalGestaltStream({ signal: SIGNAL_GREEN, data: [value] })).join('\n')
    const segmented = parseConversationProjection(module.ugui_project_conversation_text(adjacent, false), adjacent)
    expect(segmented.documents).toHaveLength(3)
    expect(segmented.documents.map(document => document.source).join('')).toBe(adjacent)
  }, 30_000)

  it('resolves assets beside the Electron file entrypoint', () => {
    expect(
      resolveUguiModuleUrls(
        'file:///Applications/Catalyst/resources/app/catalyst/apps/desktop/dist/index.html#/session'
      )
    ).toEqual([
      'file:///Applications/Catalyst/resources/app/catalyst/apps/desktop/dist/wasm/ugui_gestalt_wasm.js',
      'file:///Applications/Catalyst/resources/app/catalyst/apps/desktop/dist/wasm/catalyst_wasm.js'
    ])
  })

  it('retains the Vite origin in development', () => {
    expect(resolveUguiModuleUrls('http://127.0.0.1:5174/#/session')).toEqual([
      'http://127.0.0.1:5174/wasm/ugui_gestalt_wasm.js',
      'http://127.0.0.1:5174/wasm/catalyst_wasm.js'
    ])
  })

  it('binds each generated module to its exact sibling WASM asset', () => {
    expect(
      resolveUguiWasmUrl(
        'file:///Applications/Catalyst/resources/app/catalyst/apps/desktop/dist/wasm/ugui_gestalt_wasm.js'
      )
    ).toBe(
      'file:///Applications/Catalyst/resources/app/catalyst/apps/desktop/dist/wasm/ugui_gestalt_wasm_bg.wasm'
    )
    expect(resolveUguiWasmUrl('http://127.0.0.1:5174/wasm/catalyst_wasm.js')).toBe(
      'http://127.0.0.1:5174/wasm/catalyst_wasm_bg.wasm'
    )
  })

  it('initializes generated glue with the explicit WASM URL', async () => {
    const initialize = vi.fn(async () => undefined)
    const moduleUrl = 'http://127.0.0.1:5174/wasm/ugui_gestalt_wasm.js'

    await initializeUguiModule({ default: initialize }, moduleUrl)

    expect(initialize).toHaveBeenCalledOnce()
    expect(initialize).toHaveBeenCalledWith({
      module_or_path: 'http://127.0.0.1:5174/wasm/ugui_gestalt_wasm_bg.wasm'
    })
  })

  it('loads packaged file URL WASM through the narrow Electron bridge', async () => {
    const initialize = vi.fn(async () => undefined)
    const bytes = new Uint8Array([0, 97, 115, 109])
    const readPackagedWasm = vi.fn(async () => bytes)

    await initializeUguiModule(
      { default: initialize },
      'file:///Applications/Catalyst/resources/app/catalyst/apps/desktop/dist/wasm/ugui_gestalt_wasm.js',
      readPackagedWasm
    )

    expect(readPackagedWasm).toHaveBeenCalledWith('ugui_gestalt_wasm_bg.wasm')
    expect(initialize).toHaveBeenCalledWith({ module_or_path: bytes })
  })
})
