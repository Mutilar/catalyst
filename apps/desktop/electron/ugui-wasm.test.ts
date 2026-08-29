import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import { test } from 'vitest'

import { readPackagedUguiWasm, resolvePackagedUguiWasmPath } from './ugui-wasm'

test('packaged UGUI WASM resolver admits only owned binary names', () => {
  assert.equal(
    resolvePackagedUguiWasmPath('/app', 'ugui_gestalt_wasm_bg.wasm'),
    path.join('/app', 'dist', 'wasm', 'ugui_gestalt_wasm_bg.wasm')
  )
  assert.throws(() => resolvePackagedUguiWasmPath('/app', '../outside.wasm'), /not admitted/)
  assert.throws(() => resolvePackagedUguiWasmPath('/app', 'arbitrary.wasm'), /not admitted/)
})

test('packaged UGUI WASM reader returns bounded binary bytes', async () => {
  const appRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'catalyst-ugui-wasm-'))
  const wasmDir = path.join(appRoot, 'dist', 'wasm')
  fs.mkdirSync(wasmDir, { recursive: true })
  fs.writeFileSync(path.join(wasmDir, 'ugui_gestalt_wasm_bg.wasm'), Buffer.from([0, 97, 115, 109]))

  try {
    const bytes = await readPackagedUguiWasm(appRoot, 'ugui_gestalt_wasm_bg.wasm')
    assert.deepEqual([...bytes], [0, 97, 115, 109])
  } finally {
    fs.rmSync(appRoot, { recursive: true, force: true })
  }
})
