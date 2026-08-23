import { describe, expect, it, vi } from 'vitest'

import { initializeUguiModule, resolveUguiModuleUrls, resolveUguiWasmUrl } from './ugui-engine'

describe('UGUI WASM module resolution', () => {
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
