import { spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const repository = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..')

if (process.argv.length !== 3 || process.argv[2] !== '--check') {
  console.error('usage: node catalyst/scripts/quality/coverage.mjs --check')
  process.exit(2)
}

// The pinned tooling overlay leaves the existing project lock and runtime pins unchanged.
const version = '7.16.1'
const profile = [
  'run', '--directory', 'catalyst', '--frozen', '--offline',
  '--extra', 'dev', '--extra', 'all', '--with', `coverage==${version}`,
  '--index-url', 'https://pypi.tuna.tsinghua.edu.cn/simple'
]
const temporary = mkdtempSync(path.join(process.platform === 'darwin' ? '/tmp' : tmpdir(), 'cc-'))
process.on('exit', () => rmSync(temporary, { recursive: true, force: true }))

function execute(args) {
  const result = spawnSync('uv', [...profile, ...args], {
    cwd: repository,
    env: {
      ...process.env,
      ...(process.platform === 'darwin' ? { TMPDIR: '/tmp', TMP: '/tmp', TEMP: '/tmp' } : {}),
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
  if (result.status !== 0) process.exit(result.status ?? 1)
  return result.stdout ?? ''
}

execute([
  'python', 'scripts/run_tests_parallel.py', '--coverage', '--quality-summary',
  '--include-integration', '--file-retries', '0', '--file-timeout', '300',
  '--jobs', '8', '--slice', '1/1', 'tests', '--', '-q'
])
execute(['coverage', 'combine'])
const reportPath = path.join(temporary, 'report.json')
execute(['coverage', 'json', '-o', reportPath])
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
copyFileSync(reportPath, path.join(repository, retained))
console.log(JSON.stringify({
  data: [{ totals: {
    lines: { count: totals.num_statements, covered: totals.covered_lines },
    branches: { count: totals.num_branches, covered: totals.covered_branches }
  } }],
  provenance: { tool: 'coverage.py', version, report: retained, sha256: `sha256:${hash}` }
}))
