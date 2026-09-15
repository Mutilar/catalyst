import fs from 'node:fs'
import path from 'node:path'

import { test } from 'vitest'

test('source backends require their managed dependency environments', () => {
  const source = fs.readFileSync(path.join(__dirname, 'main.ts'), 'utf8')

  if (!source.includes("const venvRoot = options.venvRoot || path.join(root, '.venv')")) {
    throw new Error('source backend does not default to the uv-managed dependency venv')
  }

  if (!source.includes('options.requireVenv ? null : findPythonForRoot(root)')) {
    throw new Error('source backend cannot refuse an unmanaged Python fallback')
  }

  if (!source.includes('createPythonBackend(overrideRoot, `Hermes source at ${overrideRoot}`, backendArgs, {')) {
    throw new Error('desktop override does not select the source backend')
  }

  if (!source.includes("const overrideSourceVenv = overrideRoot && path.join(overrideRoot, '.venv')")) {
    throw new Error('desktop override does not resolve the source uv environment')
  }

  if (!source.includes('fileExists(getVenvPython(overrideSourceVenv)) ? overrideSourceVenv : VENV_ROOT')) {
    throw new Error('desktop override does not prefer source dependencies before installed fallback')
  }

  if (!source.includes('isHermesSourceRoot(overrideRoot) && fileExists(getVenvPython(overrideVenvRoot))')) {
    throw new Error('desktop override bypasses managed-venv bootstrap readiness')
  }

  if (!source.includes('venvRoot: overrideVenvRoot')) {
    throw new Error('desktop override does not use the resolved dependency environment')
  }

  if (!source.includes('requireVenv: true')) {
    throw new Error('development source can silently fall back to system Python')
  }
})
