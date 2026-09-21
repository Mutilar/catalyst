import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const repository = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..')

if (process.argv.length !== 3 || process.argv[2] !== '--check') {
  console.error('usage: node catalyst/scripts/quality/test.mjs --check')
  process.exit(2)
}

function execute(command, args, environment = {}) {
  const result = spawnSync(command, args, {
    cwd: repository,
    env: {
      ...process.env,
      ...(process.platform === 'darwin' ? { TMPDIR: '/tmp', TMP: '/tmp', TEMP: '/tmp' } : {}),
      ...environment
    },
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
  '--directory',
  'catalyst',
  '--frozen',
  '--offline',
  '--extra',
  'dev',
  // Match the CI profile: gateway and protocol tests import these extras during collection.
  '--extra',
  'all',
  'python',
  'scripts/run_tests_parallel.py',
  '--quality-summary',
  '--include-integration',
  '--file-retries',
  '0',
  '--file-timeout',
  '300',
  '--jobs',
  '4',
  '--slice',
  '1/1',
  'tests',
  '--',
  '-q'
], { PYTEST_ADDOPTS: '' })
const desktop = execute('npm', [
  '--prefix',
  'catalyst/apps/desktop',
  'run',
  'test:ui'
])

const summaries = python.split('\n').filter(line => line.startsWith('HERMES_TEST_SUMMARY '))
let pytest
try {
  if (summaries.length === 1) pytest = JSON.parse(summaries[0].slice('HERMES_TEST_SUMMARY '.length))
} catch (error) {
  console.error(`quality summary unavailable: invalid Python summary: ${error.message}`)
  process.exit(2)
}
const fields = ['files', 'completed', 'file_failures', 'unmeasured_files', 'passed', 'failed', 'skipped', 'errors', 'xfailed', 'xpassed', 'deselected']
const vitest = desktop.match(/Tests\s+(\d+) passed(?:\s|\(|$)/m)
if (!pytest || pytest.schema !== 'hermes-test-summary/1'
  || !fields.every(field => Number.isSafeInteger(pytest[field]) && pytest[field] >= 0)
  || pytest.files === 0 || pytest.completed !== pytest.files
  || pytest.file_failures !== 0 || pytest.unmeasured_files !== 0
  || pytest.failed !== 0 || pytest.errors !== 0 || pytest.passed + pytest.xpassed === 0 || !vitest) {
  console.error('quality summary unavailable: exact passing counts and complete file execution are required')
  process.exit(2)
}
const count = (output, label) =>
  Number.parseInt(output.match(new RegExp(`(?:^|\\s)(\\d+) ${label}(?:,|\\s|$)`, 'm'))?.[1] ?? '0', 10)
const passed = pytest.passed + pytest.xpassed + Number.parseInt(vitest[1], 10)
const desktopSummary = desktop.match(/Tests[^\n]*/m)?.[0] ?? ''
const ignored = pytest.skipped + pytest.xfailed
  + count(desktopSummary, 'skipped') + count(desktopSummary, 'todo')
const filtered = pytest.deselected
console.log(`running ${passed + ignored} tests`)
console.log(
  `test result: ok. ${passed} passed; 0 failed; ${ignored} ignored; 0 measured; ${filtered} filtered out;`
)
