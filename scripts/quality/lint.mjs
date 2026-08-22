import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const repository = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..')

if (process.argv.length !== 3 || process.argv[2] !== '--check') {
  console.error('usage: node catalyst/scripts/quality/lint.mjs --check')
  process.exit(2)
}

function execute(command, args) {
  const result = spawnSync(command, args, {
    cwd: repository,
    encoding: 'utf8',
    maxBuffer: 16 * 1024 * 1024
  })
  if (result.stdout) process.stdout.write(result.stdout)
  if (result.stderr) process.stderr.write(result.stderr)
  if (result.error) {
    console.error(`${command} unavailable: ${result.error.message}`)
    process.exit(2)
  }
  if (result.status !== 0) process.exit(result.status ?? 1)
}

execute('uv', [
  'run',
  '--project',
  'catalyst',
  '--frozen',
  'ruff',
  'check',
  'catalyst'
])
execute('npm', [
  '--prefix',
  'catalyst/apps/desktop',
  'run',
  'check:lint'
])
