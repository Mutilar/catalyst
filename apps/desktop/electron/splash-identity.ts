import fs from 'node:fs'
import path from 'node:path'

function readBounded(file: string, maximum: number): string {
  const metadata = fs.lstatSync(file)

  if (!metadata.isFile() || metadata.isSymbolicLink() || metadata.size > maximum) {
    throw new Error('Invalid splash identity source')
  }

  const bytes = fs.readFileSync(file)

  if (bytes.length > maximum) {
    throw new Error('Splash identity source exceeds its bound')
  }

  return bytes.toString('utf8')
}

export function readSplashIdentity(catalystRoot: string): { alias: string; glyph: string; image: string } | null {
  try {
    const root = path.resolve(catalystRoot, '..')
    const decision = JSON.parse(readBounded(path.join(root, 'run/state/runtime/lucid-host-role.json'), 4096))

    if (
      decision.schema !== 'lucid-host-role-decision/1' ||
      typeof decision.witness_alias !== 'string' ||
      !/^[a-z][a-z0-9_-]{0,31}$/.test(decision.witness_alias) ||
      typeof decision.witness_glyph !== 'string' ||
      [...decision.witness_glyph].length > 16
    ) {
      return null
    }

    const registry = JSON.parse(readBounded(path.join(root, 'quine/author-glyphs.json'), 1024 * 1024))
    const author = registry.authors?.[decision.witness_alias]

    if (registry.schema !== 'ae-author-glyphs/1' || author !== decision.witness_glyph) {
      return null
    }

    const code = [...decision.witness_glyph]
      .filter(character => character !== '\ufe0f')
      .map(character => character.codePointAt(0)!.toString(16))
      .join('-')

    if (!/^[a-f0-9]+(?:-[a-f0-9]+)*$/.test(code)) {
      return null
    }

    const svg = readBounded(path.join(root, `genui/ugui/assets/twemoji/animals/${code}.svg`), 128 * 1024)

    return {
      alias: decision.witness_alias,
      glyph: decision.witness_glyph,
      image: `data:image/svg+xml;base64,${Buffer.from(svg).toString('base64')}`
    }
  } catch {
    return null
  }
}
