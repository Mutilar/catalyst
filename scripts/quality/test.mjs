import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const repository = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..')

if (process.argv.length !== 3 || process.argv[2] !== '--check') {
  console.error('usage: node catalyst/scripts/quality/test.mjs --check')
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
  return `${result.stdout ?? ''}\n${result.stderr ?? ''}`
}

const python = execute('uv', [
  'run',
  '--project',
  'catalyst',
  '--frozen',
  '--offline',
  '--extra',
  'dev',
  'pytest',
  'catalyst/tests',
  '-q'
])
const desktop = execute('npm', [
  '--prefix',
  'catalyst/apps/desktop',
  'run',
  'test:ui'
])

const pytest = python.match(/(?:^|\s)(\d+) passed(?:,|\s|$)/m)
const vitest = desktop.match(/Tests\s+(\d+) passed(?:\s|\(|$)/m)
if (!pytest || !vitest) {
  console.error('quality summary unavailable: pytest or Vitest did not report exact passed counts')
  process.exit(2)
}
const passed = Number.parseInt(pytest[1], 10) + Number.parseInt(vitest[1], 10)
console.log(`running ${passed} tests`)
console.log(
  `test result: ok. ${passed} passed; 0 failed; 0 ignored; 0 measured; 0 filtered out;`
)
