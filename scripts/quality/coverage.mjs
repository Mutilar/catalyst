import { runCommand } from './command.mjs'
import { createHash } from 'node:crypto'
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, statSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const repository = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..')

const checking = process.argv.length === 3 && process.argv[2] === '--check'
const summarizing = process.argv.length === 4 && process.argv[2] === '--summarize'
if (!checking && !summarizing) {
  console.error('usage: node catalyst/scripts/quality/coverage.mjs --check | --summarize REPORT_PATH')
  process.exit(2)
}

// The pinned tooling overlay leaves the existing project lock and runtime pins unchanged.
const version = '7.16.1'
const profile = [
  'run', '--directory', 'catalyst', '--frozen', '--offline',
  '--extra', 'dev', '--extra', 'all', '--with', `coverage==${version}`,
  '--index-url', 'https://pypi.tuna.tsinghua.edu.cn/simple'
]
const temporary = mkdtempSync(path.join(tmpdir(), 'cc-'))
process.on('exit', () => rmSync(temporary, { recursive: true, force: true }))

async function execute(args, retainAfterFailure = false) {
  const result = await runCommand('uv', [...profile, ...args], {
    cwd: repository,
    env: {
      ...process.env,
      PYTEST_ADDOPTS: '',
      COVERAGE_FILE: path.join(temporary, '.coverage')
    },
    encoding: 'utf8',
    maxBuffer: 16 * 1024 * 1024
  })
  if (result.stdout) process.stdout.write(result.stdout)
  if (result.stderr) process.stderr.write(result.stderr)
  if (result.error) {
    console.error(`uv unavailable: ${result.error.message}`)
    process.exit(2)
  }
  if (!Number.isInteger(result.status)) {
    console.error(`coverage subprocess terminated without an exit status: ${result.signal ?? 'unknown'}`)
    process.exit(2)
  }
  if (result.status !== 0 && !retainAfterFailure) process.exit(result.status)
  return result.status
}

let testExitCode = null
let rawProvenance = {}
let reportPath = path.join(temporary, 'report.json')
if (checking) {
  testExitCode = await execute([
    'python', 'scripts/run_tests_parallel.py', '--coverage', '--quality-summary',
    '--include-integration', '--file-retries', '0', '--file-timeout', '300',
    '--jobs', '8', '--slice', '1/1', 'tests', '--', '-q'
  ], true)
  await execute(['coverage', 'combine'])
  const rawPath = path.join(temporary, '.coverage')
  const rawHash = createHash('sha256').update(readFileSync(rawPath)).digest('hex')
  const retainedRaw = path.join('catalyst', '.pytest_cache', 'quality-coverage', `${rawHash}.coverage`)
  mkdirSync(path.dirname(path.join(repository, retainedRaw)), { recursive: true })
  copyFileSync(rawPath, path.join(repository, retainedRaw))
  console.error(`merged coverage retained: ${retainedRaw}`)
  rawProvenance = { data: retainedRaw, data_sha256: `sha256:${rawHash}` }
  await execute(['coverage', 'json', '-o', reportPath])
} else {
  reportPath = realpathSync(path.resolve(repository, process.argv[3]))
  if (!reportPath.startsWith(`${realpathSync(path.join(repository, 'catalyst'))}${path.sep}`)) {
    console.error('coverage report must belong to catalyst')
    process.exit(2)
  }
}
const metadata = statSync(reportPath)
if (!metadata.isFile() || metadata.size > 128 * 1024 * 1024) {
  console.error('coverage report must be a bounded regular file')
  process.exit(2)
}
const bytes = readFileSync(reportPath)
const report = JSON.parse(bytes.toString('utf8'))
const totals = report.totals
const fields = ['num_statements', 'covered_lines', 'num_branches', 'covered_branches']
if (report.meta?.version !== version || report.meta?.branch_coverage !== true
  || !totals || !fields.every(field => Number.isSafeInteger(totals[field]) && totals[field] >= 0)
  || totals.covered_lines > totals.num_statements || totals.covered_branches > totals.num_branches) {
  console.error('quality coverage summary unavailable: complete exact branch-aware coverage counts are required')
  process.exit(2)
}
const hash = createHash('sha256').update(bytes).digest('hex')
const retained = path.join('catalyst', '.pytest_cache', 'quality-coverage', `${hash}.json`)
mkdirSync(path.dirname(path.join(repository, retained)), { recursive: true })
if (path.resolve(reportPath) !== path.join(repository, retained)) {
  copyFileSync(reportPath, path.join(repository, retained))
}
const retainedSummary = path.join('catalyst', '.pytest_cache', 'quality-coverage', `${hash}.summary.json`)
const summary = JSON.stringify({
  data: [{ totals: {
    lines: { count: totals.num_statements, covered: totals.covered_lines },
    branches: { count: totals.num_branches, covered: totals.covered_branches }
  } }],
  provenance: {
    tool: 'coverage.py', version, report: retained, sha256: `sha256:${hash}`,
    ...rawProvenance, summary: retainedSummary, test_exit_code: testExitCode
  }
})
writeFileSync(path.join(repository, retainedSummary), `${summary}\n`)
console.log(summary)
if (testExitCode !== null && testExitCode !== 0) {
  console.error(`test execution failed (exit ${testExitCode}); measured coverage retained without qualification`)
}
process.exitCode = testExitCode ?? 0
