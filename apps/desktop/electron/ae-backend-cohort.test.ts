import fs from 'node:fs'
import path from 'node:path'

import { test } from 'vitest'

test('packaged source override uses AE source with the active managed venv', () => {
  const source = fs.readFileSync(path.join(__dirname, 'main.ts'), 'utf8')

  if (!source.includes("const venvRoot = options.venvRoot || path.join(root, 'venv')")) {
    throw new Error('source backend does not accept an explicit dependency venv')
  }
  if (!source.includes('createPythonBackend(overrideRoot, `Hermes source at ${overrideRoot}`, backendArgs, {')) {
    throw new Error('desktop override does not select the source backend')
  }
  if (!source.includes('isHermesSourceRoot(overrideRoot) && fileExists(getVenvPython(VENV_ROOT))')) {
    throw new Error('desktop override bypasses managed-venv bootstrap readiness')
  }
  if (!source.includes('venvRoot: VENV_ROOT')) {
    throw new Error('desktop override does not reuse the active managed venv')
  }
})
