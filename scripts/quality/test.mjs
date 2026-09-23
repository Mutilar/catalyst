import { runCommand } from './command.mjs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const repository = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..')

if (process.argv.length !== 3 || process.argv[2] !== '--check') {
  console.error('usage: node catalyst/scripts/quality/test.mjs --check')
  process.exit(2)
}

async function execute(command, args, environment = {}, summaryMarker) {
  const result = await runCommand(command, args, {
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
  const output = `${result.stdout ?? ''}\n${result.stderr ?? ''}`
  if (result.status === null) process.exit(1)
  if (result.status !== 0 && !summaryMarker.test(output)) process.exit(result.status)
  return { output, status: result.status }
}

const python = await execute('uv', [
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
], { PYTEST_ADDOPTS: '' }, /^HERMES_TEST_SUMMARY /m)
const desktop = await execute('npm', [
  '--prefix',
  'catalyst/apps/desktop',
  'run',
  'test:ui'
], {}, /^\s*Tests\s+/m)

const summaries = python.output.split('\n').filter(line => line.startsWith('HERMES_TEST_SUMMARY '))
let pytest
try {
  if (summaries.length === 1) pytest = JSON.parse(summaries[0].slice('HERMES_TEST_SUMMARY '.length))
} catch (error) {
  console.error(`quality summary unavailable: invalid Python summary: ${error.message}`)
  process.exit(2)
}
const fields = ['files', 'completed', 'file_failures', 'unmeasured_files', 'passed', 'failed', 'skipped', 'errors', 'xfailed', 'xpassed', 'deselected']
const desktopSummary = desktop.output.match(/^\s*Tests\s+([^\n]+)/m)?.[1]
const count = (output, label) =>
  Number.parseInt(output.match(new RegExp(`(?:^|\\s)(\\d+) ${label}(?:,|\\s|$)`, 'm'))?.[1] ?? '0', 10)
const desktopPassed = desktopSummary ? count(desktopSummary, 'passed') : 0
const desktopFailed = desktopSummary ? count(desktopSummary, 'failed') : 0
if (!pytest || pytest.schema !== 'hermes-test-summary/1'
  || !fields.every(field => Number.isSafeInteger(pytest[field]) && pytest[field] >= 0)
  || pytest.files === 0 || pytest.completed !== pytest.files
  || pytest.unmeasured_files !== 0
  || (pytest.file_failures > 0 && pytest.failed + pytest.errors === 0)
  || !desktopSummary
  || pytest.passed + pytest.xpassed + pytest.failed + pytest.errors === 0
  || desktopPassed + desktopFailed === 0
  || (python.status === 0) !== (pytest.failed + pytest.errors + pytest.file_failures === 0)
  || (desktop.status === 0) !== (desktopFailed === 0)) {
  console.error('quality summary unavailable: consistent measured counts and complete file execution are required')
  process.exit(python.status || desktop.status || 2)
}
const passed = pytest.passed + pytest.xpassed + desktopPassed
const failed = pytest.failed + pytest.errors + desktopFailed
const ignored = pytest.skipped + pytest.xfailed
  + count(desktopSummary, 'skipped') + count(desktopSummary, 'todo')
const filtered = pytest.deselected
console.log(`running ${passed + failed + ignored} tests`)
console.log(
  `test result: ${failed ? 'FAILED' : 'ok'}. ${passed} passed; ${failed} failed; ${ignored} ignored; 0 measured; ${filtered} filtered out;`
)
process.exit(python.status || desktop.status || 0)
