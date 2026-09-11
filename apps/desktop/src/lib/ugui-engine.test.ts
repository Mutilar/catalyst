import { readFile } from 'node:fs/promises'
import { describe, expect, it, vi } from 'vitest'

import { DELIMITER_SEGMENT, RELATION_ACTION, SIGNAL_GREEN } from './ae-glyphs'
import { canonicalGestaltStream } from './lucid-gestalt'

import { initializeUguiModule, resolveUguiModuleUrls, resolveUguiWasmUrl } from './ugui-engine'

describe('UGUI WASM module resolution', () => {
  it('projects through the actual generated conversation ABI, not a mocked document', async () => {
    const module = await import('../../public/wasm/ugui_gestalt_wasm.js')
    const bytes = await readFile(new URL('../../public/wasm/ugui_gestalt_wasm_bg.wasm', import.meta.url))
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
