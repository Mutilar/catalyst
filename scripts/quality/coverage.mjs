import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const repository = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..')

if (process.argv.length !== 3 || process.argv[2] !== '--check') {
  console.error('usage: node catalyst/scripts/quality/coverage.mjs --check')
  process.exit(2)
}

function execute(args, capture = false) {
  const result = spawnSync('uv', args, {
    cwd: repository,
    encoding: 'utf8',
    maxBuffer: 16 * 1024 * 1024
  })
  if (!capture && result.stdout) process.stdout.write(result.stdout)
  if (result.stderr) process.stderr.write(result.stderr)
  if (result.error) {
    console.error(`uv unavailable: ${result.error.message}`)
    process.exit(2)
  }
  if (result.status !== 0) process.exit(result.status ?? 1)
  return result.stdout ?? ''
}

execute([
  'run',
  '--project',
  'catalyst',
  '--frozen',
  'coverage',
  'run',
  '--branch',
  '--source=catalyst',
  '-m',
  'pytest',
  'catalyst/tests',
  '-q'
])
const report = execute([
  'run',
  '--project',
  'catalyst',
  '--frozen',
  'coverage',
  'json',
  '-o',
  '-'
], true)
process.stdout.write(report)
