const SEMANTIC_OBSERVATION_PREFIXES = ['CATALYST_TOOL_OBSERVATION ', 'PENGUIN_TEACHING_EVENT '] as const
const EFFIGY_WARNING = /^⚠️ [^\s·]{1,16} · 🔎 [a-z0-9][a-z0-9-]{0,95}(?:: \S.{0,256})?$/u

const MAX_SEMANTIC_OBSERVATION_BYTES = 8 * 1024

export type SemanticObservationWriter = (line: string) => void

export function createSemanticObservationForwarder(write: SemanticObservationWriter) {
  let pending = ''

  return (chunk: string | Buffer) => {
    pending += String(chunk)
    if (Buffer.byteLength(pending, 'utf8') > MAX_SEMANTIC_OBSERVATION_BYTES * 2) {
      pending = ''
      return
    }

    let newline = pending.indexOf('\n')
    while (newline >= 0) {
      const line = pending.slice(0, newline).replace(/\r$/, '')
      pending = pending.slice(newline + 1)
      if (
        Buffer.byteLength(line, 'utf8') <= MAX_SEMANTIC_OBSERVATION_BYTES &&
        (SEMANTIC_OBSERVATION_PREFIXES.some(prefix => line.startsWith(prefix)) || EFFIGY_WARNING.test(line))
      ) {
        write(`${line}\n`)
      }
      newline = pending.indexOf('\n')
    }
  }
}
