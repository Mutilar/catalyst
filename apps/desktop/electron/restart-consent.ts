import fs from 'node:fs'
import path from 'node:path'

export const RESTART_INTENT_SCHEMA = 'run-catalyst-restart-intent/1'
export const RESTART_DECISION_SCHEMA = 'run-catalyst-restart-decision/1'
const MAX_STATE_BYTES = 16 * 1024
const DIGEST = /^sha256:[0-9a-f]{64}$/
const INTENT_ID = /^restart:[0-9a-f]{64}$/

export interface CatalystRestartIntent {
  schema: typeof RESTART_INTENT_SCHEMA
  child_id: 'catalyst'
  generation_hash: string
  intent_id: string
  observed_epoch_ms: number
  owner: 'RUN'
  reason: 'source-build-prepared'
  state: 'deferred' | 'pending'
}

export interface CatalystRestartDecisionRequest {
  action: 'accept' | 'defer'
  generation_hash: string
  intent_id: string
}

function stateRoot(repoRoot: string) {
  return path.join(repoRoot, 'run', 'state', 'runtime')
}

function intentPath(repoRoot: string) {
  return path.join(stateRoot(repoRoot), 'catalyst-restart-intent.json')
}

function boundedJson(file: string): unknown {
  const stat = fs.lstatSync(file)

  if (!stat.isFile() || stat.isSymbolicLink() || stat.size > MAX_STATE_BYTES) {
    throw new Error('Catalyst restart state is invalid')
  }

  return JSON.parse(fs.readFileSync(file, 'utf8')) as unknown
}

export function readCatalystRestartIntent(repoRoot: string): CatalystRestartIntent | null {
  try {
    const value = boundedJson(intentPath(repoRoot)) as Partial<CatalystRestartIntent>

    if (
      value.schema !== RESTART_INTENT_SCHEMA ||
      value.child_id !== 'catalyst' ||
      !INTENT_ID.test(value.intent_id || '') ||
      !DIGEST.test(value.generation_hash || '') ||
      !Number.isSafeInteger(value.observed_epoch_ms) ||
      value.owner !== 'RUN' ||
      value.reason !== 'source-build-prepared' ||
      (value.state !== 'pending' && value.state !== 'deferred')
    ) {
      return null
    }

    return value as CatalystRestartIntent
  } catch {
    return null
  }
}

export function decideCatalystRestart(
  repoRoot: string,
  request: CatalystRestartDecisionRequest
): { accepted: true; action: 'accept' | 'defer'; intent_id: string } {
  if (
    !request ||
    (request.action !== 'accept' && request.action !== 'defer') ||
    !INTENT_ID.test(request.intent_id) ||
    !DIGEST.test(request.generation_hash)
  ) {
    throw new Error('Catalyst restart decision is malformed')
  }

  const current = readCatalystRestartIntent(repoRoot)

  if (
    !current ||
    current.intent_id !== request.intent_id ||
    current.generation_hash !== request.generation_hash
  ) {
    throw new Error('Catalyst restart intent was superseded; reopen the current intent')
  }

  const digest = request.generation_hash.slice('sha256:'.length)
  const directory = path.join(stateRoot(repoRoot), 'catalyst-restart-decisions')
  const target = path.join(directory, `${digest}.json`)
  const temporary = `${target}.tmp-${process.pid}-${Date.now()}`

  const decision = {
    schema: RESTART_DECISION_SCHEMA,
    child_id: 'catalyst',
    intent_id: request.intent_id,
    generation_hash: request.generation_hash,
    action: request.action,
    decided_epoch_ms: Date.now()
  }

  const bytes = Buffer.from(JSON.stringify(decision), 'utf8')

  if (bytes.byteLength > MAX_STATE_BYTES) {
    throw new Error('Catalyst restart decision exceeds its bound')
  }

  fs.mkdirSync(directory, { recursive: true, mode: 0o700 })
  fs.writeFileSync(temporary, bytes, { flag: 'wx', mode: 0o600 })

  try {
    fs.renameSync(temporary, target)
  } catch (error) {
    try {
      fs.rmSync(target, { force: true })
      fs.renameSync(temporary, target)
    } catch {
      fs.rmSync(temporary, { force: true })
      throw error
    }
  }

  return { accepted: true, action: request.action, intent_id: request.intent_id }
}
