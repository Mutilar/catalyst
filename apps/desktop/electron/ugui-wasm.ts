import fs from 'node:fs'
import path from 'node:path'

const UGUI_WASM_ASSETS = new Set(['catalyst_wasm_bg.wasm', 'ugui_gestalt_wasm_bg.wasm'])
const MAX_UGUI_WASM_BYTES = 16 * 1024 * 1024

export function resolvePackagedUguiWasmPath(appRoot: string, assetName: unknown): string {
  if (typeof assetName !== 'string' || !UGUI_WASM_ASSETS.has(assetName)) {
    throw new Error('UGUI WASM asset is not admitted')
  }

  return path.join(appRoot, 'dist', 'wasm', assetName)
}

export async function readPackagedUguiWasm(appRoot: string, assetName: unknown): Promise<Uint8Array> {
  const assetPath = resolvePackagedUguiWasmPath(appRoot, assetName)
  const stat = await fs.promises.stat(assetPath)

  if (!stat.isFile() || stat.size === 0 || stat.size > MAX_UGUI_WASM_BYTES) {
    throw new Error('UGUI WASM asset is missing, empty, or exceeds its bound')
  }

  return fs.promises.readFile(assetPath)
}
