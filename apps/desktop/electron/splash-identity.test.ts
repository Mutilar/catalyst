import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { readSplashIdentity } from './splash-identity'

describe('read-only WITNESS splash identity', () => {
  let root: string
  const decision = {
    schema: 'lucid-host-role-decision/1',
    role: 'WITNESS',
    witness_alias: 'brianhu',
    witness_glyph: '🐧'
  }

  function write(relative: string, text: string) {
    fs.mkdirSync(path.dirname(path.join(root, relative)), { recursive: true })
    fs.writeFileSync(path.join(root, relative), text)
  }

  beforeEach(() => {
    root = fs.mkdtempSync(path.join(os.tmpdir(), 'splash-identity-'))
    write('run/state/runtime/lucid-host-role.json', JSON.stringify(decision))
    write('quine/author-glyphs.json', JSON.stringify({ schema: 'ae-author-glyphs/1', authors: { brianhu: '🐧' } }))
    write(
      'genui/ugui/assets/twemoji/animals/1f427.svg',
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 36 36"/>'
    )
  })
  afterEach(() => fs.rmSync(root, { recursive: true, force: true }))

  it('returns only display identity and a local vector asset', () => {
    const result = readSplashIdentity(path.join(root, 'catalyst'))
    expect(result).toEqual({
      alias: 'brianhu',
      glyph: '🐧',
      image: expect.stringMatching(/^data:image\/svg\+xml;base64,/)
    })
  })
  it('rejects mismatched identities instead of choosing another registered user', () => {
    write('run/state/runtime/lucid-host-role.json', JSON.stringify({ ...decision, witness_glyph: '🦊' }))
    expect(readSplashIdentity(path.join(root, 'catalyst'))).toBeNull()
  })
  it('rejects missing, oversized, malformed, and symlinked decisions', () => {
    const target = path.join(root, 'run/state/runtime/lucid-host-role.json')

    for (const text of ['{', ' '.repeat(4097)]) {
      fs.writeFileSync(target, text)
      expect(readSplashIdentity(path.join(root, 'catalyst'))).toBeNull()
    }

    fs.unlinkSync(target)
    expect(readSplashIdentity(path.join(root, 'catalyst'))).toBeNull()
    write('other.json', JSON.stringify(decision))
    fs.symlinkSync(path.join(root, 'other.json'), target)
    expect(readSplashIdentity(path.join(root, 'catalyst'))).toBeNull()
  })
  it('does not substitute raster or missing artwork', () => {
    fs.unlinkSync(path.join(root, 'genui/ugui/assets/twemoji/animals/1f427.svg'))
    expect(readSplashIdentity(path.join(root, 'catalyst'))).toBeNull()
  })
})
