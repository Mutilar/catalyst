import assert from 'node:assert/strict'

import { test } from 'vitest'

import viteConfig from '../vite.config'

test('renderer builds preserve the live Electron main and preload pair', () => {
  const config = viteConfig as { build?: { emptyOutDir?: boolean } }

  assert.equal(config.build?.emptyOutDir, false)
})