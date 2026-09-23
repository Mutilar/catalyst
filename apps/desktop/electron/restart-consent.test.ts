import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import { afterEach, describe, expect, it } from 'vitest'

import { decideCatalystRestart, readCatalystRestartIntent, RESTART_INTENT_SCHEMA } from './restart-consent'

const roots: string[] = []

function root() {
  const value = fs.mkdtempSync(path.join(os.tmpdir(), 'catalyst-restart-consent-'))
  roots.push(value)

  return value
}

function publishIntent(repoRoot: string, byte = 'a', state: 'deferred' | 'pending' = 'pending') {
  const digest = byte.repeat(64)

  const intent = {
    schema: RESTART_INTENT_SCHEMA,
    child_id: 'catalyst',
    intent_id: `restart:${digest}`,
    generation_hash: `sha256:${digest}`,
    state,
    reason: 'source-build-prepared',
    owner: 'RUN',
    observed_epoch_ms: 42
  }

  const directory = path.join(repoRoot, 'run/state/runtime')
  fs.mkdirSync(directory, { recursive: true })
  fs.writeFileSync(path.join(directory, 'catalyst-restart-intent.json'), JSON.stringify(intent))

  return intent
}

afterEach(() => {
  roots.splice(0).forEach(value => fs.rmSync(value, { force: true, recursive: true }))
})

describe('Catalyst restart consent bridge', () => {
  it('keeps preload channels paired with main-process handlers', () => {
    const preload = fs.readFileSync(path.join(__dirname, 'preload.ts'), 'utf8')
    const main = fs.readFileSync(path.join(__dirname, 'main.ts'), 'utf8')

    for (const channel of ['hermes:restart-consent:get', 'hermes:restart-consent:decide']) {
      expect(preload).toContain(`ipcRenderer.invoke('${channel}'`)
      expect(main).toContain(`ipcMain.handle('${channel}'`)
    }
  })

  it('reads only a closed RUN-owned intent and writes one hash-addressed decision', () => {
    const repoRoot = root()
    const intent = publishIntent(repoRoot)

    expect(readCatalystRestartIntent(repoRoot)).toEqual(intent)
    expect(
      decideCatalystRestart(repoRoot, {
        action: 'defer',
        generation_hash: intent.generation_hash,
        intent_id: intent.intent_id
      })
    ).toEqual({ accepted: true, action: 'defer', intent_id: intent.intent_id })

    const decision = JSON.parse(
      fs.readFileSync(
        path.join(repoRoot, 'run/state/runtime/catalyst-restart-decisions', `${'a'.repeat(64)}.json`),
        'utf8'
      )
    )

    expect(decision).toMatchObject({
      action: 'defer',
      generation_hash: intent.generation_hash,
      intent_id: intent.intent_id,
      schema: 'run-catalyst-restart-decision/1'
    })
  })

  it('refuses a stale decision after RUN supersedes the intent', () => {
    const repoRoot = root()
    const stale = publishIntent(repoRoot, 'a')
    publishIntent(repoRoot, 'b')

    expect(() =>
      decideCatalystRestart(repoRoot, {
        action: 'accept',
        generation_hash: stale.generation_hash,
        intent_id: stale.intent_id
      })
    ).toThrow('superseded')
  })

  it('returns null for malformed, symlinked, or absent intent state', () => {
    const repoRoot = root()
    expect(readCatalystRestartIntent(repoRoot)).toBeNull()
    const intent = publishIntent(repoRoot)
    const file = path.join(repoRoot, 'run/state/runtime/catalyst-restart-intent.json')
    fs.writeFileSync(file, JSON.stringify({ ...intent, owner: 'CATALYST' }))
    expect(readCatalystRestartIntent(repoRoot)).toBeNull()
  })
})
