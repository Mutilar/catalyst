import { spawn } from 'node:child_process'

const shutdownGraceMs = 1_500

// Each invocation owns a new group. Keep the event loop available so RUN's TERM can
// reach uv/npm and the Python runner, which in turn owns its separate worker sessions.
export function runCommand(command, args, options) {
  return new Promise(resolve => {
    const { maxBuffer = 16 * 1024 * 1024, encoding = 'utf8', ...spawnOptions } = options
    const child = spawn(command, args, {
      ...spawnOptions,
      detached: process.platform !== 'win32',
      stdio: ['ignore', 'pipe', 'pipe']
    })
    const buffers = { stdout: [], stderr: [] }
    const sizes = { stdout: 0, stderr: 0 }
    let error
    let interrupted
    let killTimer
    let closeTimer
    let settled = false
    const signalChild = signal => {
      try {
        if (process.platform !== 'win32' && child.pid) process.kill(-child.pid, signal)
        else child.kill(signal)
      } catch (failure) {
        if (failure.code !== 'ESRCH') error ??= failure
      }
    }
    const finish = (status, signal) => {
      if (settled) return
      settled = true
      clearTimeout(killTimer)
      clearTimeout(closeTimer)
      process.off('SIGTERM', onTerm)
      process.off('SIGINT', onInt)
      resolve({
        status: interrupted ? null : status,
        signal: interrupted ?? signal,
        error,
        stdout: Buffer.concat(buffers.stdout).toString(encoding),
        stderr: Buffer.concat(buffers.stderr).toString(encoding)
      })
    }
    const closeGroup = signal => {
      signalChild(signal)
      if (killTimer) return
      killTimer = setTimeout(() => signalChild('SIGKILL'), shutdownGraceMs)
      closeTimer = setTimeout(() => {
        error ??= new Error('owned command did not close after bounded termination')
        signalChild('SIGKILL')
        child.stdout?.destroy()
        child.stderr?.destroy()
        finish(null, signal)
      }, shutdownGraceMs * 2)
    }
    const stop = signal => {
      if (interrupted) return
      interrupted = signal
      closeGroup(signal)
    }
    const onTerm = () => stop('SIGTERM')
    const onInt = () => stop('SIGINT')
    process.on('SIGTERM', onTerm)
    process.on('SIGINT', onInt)
    for (const name of ['stdout', 'stderr']) {
      child[name].on('data', chunk => {
        const remaining = Math.max(0, maxBuffer - sizes[name])
        if (remaining) buffers[name].push(chunk.subarray(0, remaining))
        sizes[name] += chunk.length
        if (sizes[name] > maxBuffer) {
          error ??= new Error(`${name} exceeded maxBuffer`)
          stop('SIGTERM')
        }
      })
    }
    child.once('error', failure => { error ??= failure })
    child.once('exit', () => {
      if (!interrupted && child.pid) closeGroup('SIGTERM')
    })
    child.once('close', (status, signal) => {
      // A closed leader pipe is not proof that its ignored-stdio descendants
      // exited. Close the owned group before releasing its escalation timer.
      if (process.platform !== 'win32' && child.pid) signalChild('SIGKILL')
      finish(status, signal)
    })
  })
}
