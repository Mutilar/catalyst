import { describe, expect, it } from 'vitest'

import { resolveUguiModuleUrls } from './ugui-engine'

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
})
