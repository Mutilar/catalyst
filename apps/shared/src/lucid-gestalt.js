import gestaltContract from '../../../../envelope/GESTALT.json'

const segments = gestaltContract.segments
const glyphs = segments.glyphs
const fields = ['signal', 'service', 'verb', 'noun', 'argument', 'evidence', 'datum', 'timing', 'action']
const asciiUpper = value => value.replace(/[a-z]/g, character => character.toUpperCase())
const asciiLower = value => value.replace(/[A-Z]/g, character => character.toLowerCase())

if (
  gestaltContract.schema !== 'lucid-gestalt/1' ||
  segments.order.join() !== fields.join() ||
  segments.required.join() !== 'signal' ||
  segments.optional.join() !== fields.slice(1).join() ||
  segments.repeatable.join() !== 'argument,evidence,datum,timing,action' ||
  segments.signals.length !== 4 ||
  ![segments.separator, ...fields.slice(1).map(field => glyphs[field]), ...segments.signals].every(
    value => typeof value === 'string' && value.length > 0
  ) ||
  [...segments.verbs].sort().join() !== Object.keys(segments.operationSelectors).sort().join() ||
  !gestaltContract.lint.alternateSeparators.every(value => typeof value === 'string' && value.length > 0) ||
  !Number.isInteger(gestaltContract.recovery.bounds.nesting) ||
  gestaltContract.recovery.bounds.nesting <= 0
) {
  throw new Error('GESTALT segment contract is invalid')
}

export function canonicalGestaltStream(stream) {
  if (!segments.signals.includes(stream.signal)) {
    throw new Error('GESTALT signal is not canonical')
  }
  if (stream.withoutIdentity && stream.service != null) {
    throw new Error('GESTALT service conflicts with withoutIdentity')
  }
  const values = [stream.signal]
  if (!stream.withoutIdentity && stream.service !== null) {
    const service = stream.service ?? glyphs.service
    validateService(service)
    values.push(service)
  }
  values.push(...coordinate(stream.verb, stream.noun, argumentValues(stream)))
  for (const [glyph, entries] of [
    [glyphs.evidence, stream.evidence],
    [glyphs.datum, stream.data]
  ]) {
    for (const entry of arrayField(entries)) values.push(`${glyph} ${semanticValue(entry)}`)
  }
  for (const entry of arrayField(stream.timing)) {
    const value = semanticValue(entry)
    values.push(isTiming(value) ? value : `${glyphs.timing} ${value}`)
  }
  const continuations = arrayField(stream.continuations).map(entry =>
    typeof entry === 'string' ? { kind: 'service', value: entry } : entry
  )
  for (const entry of continuations) {
    if (!entry || Object.keys(entry).sort().join() !== 'kind,value') {
      throw new Error('GESTALT CYOA continuation is invalid')
    }
    if (entry.kind === 'service') {
      validateService(entry.value)
      values.push(`${glyphs.action} ${entry.value}`)
    } else if (entry.kind === 'cli' || entry.kind === 'intent') {
      values.push(renderContinuation(entry.value, entry.kind === 'cli' ? '`' : '"'))
    } else {
      throw new Error('GESTALT CYOA continuation is invalid')
    }
  }
  for (const [delimiter, kind, entries] of [
    ['"', 'intent', stream.intents],
    ['`', 'cli', stream.cli]
  ]) {
    const aliases = arrayField(entries)
    const represented = continuations.filter(entry => entry.kind === kind).map(entry => entry.value)
    if (represented.length > 0 && aliases.length > 0) {
      if (represented.length !== aliases.length || represented.some((value, index) => value !== aliases[index])) {
        throw new Error('GESTALT CYOA continuation sources conflict')
      }
      continue
    }
    for (const value of aliases) values.push(renderContinuation(value, delimiter))
  }
  for (const edge of arrayField(stream.actions)) {
    if (!edge || !segments.verbs.includes(edge.verb)) {
      throw new Error('GESTALT action coordinate is invalid')
    }
    if (edge.service !== undefined && edge.service !== glyphs.service) {
      throw new Error('GESTALT executable action service is not LUCID')
    }
    values.push(`${glyphs.action} ${glyphs.service}`, ...coordinate(edge.verb, edge.noun, argumentValues(edge)))
    if (edge.label != null) values.push(`${glyphs.evidence} ${semanticValue(edge.label)}`)
  }
  return values.join(segments.separator)
}

export function parseGestaltStream(value) {
  const parts = streamParts(value)
  const signal = parts.shift()
  if (!signal || !segments.signals.includes(signal)) throw new Error('GESTALT signal is invalid')
  const service = isService(parts[0]) ? parts.shift() : null
  const stream = {
    signal,
    service,
    evidence: [],
    data: [],
    timing: [],
    continuations: [],
    intents: [],
    cli: [],
    actions: []
  }
  parseCoordinate(parts, stream)
  while (parts.length > 0) {
    const part = parts.shift()
    const actionPrefix = `${glyphs.action} `
    if (part.startsWith(actionPrefix)) {
      const payload = part.slice(actionPrefix.length)
      if (payload.startsWith('"') || payload.startsWith('`')) {
        const delimiter = payload[0]
        if (payload.length < 2 || !payload.endsWith(delimiter)) throw new Error('GESTALT CYOA quote is unclosed')
        const text = payload.slice(1, -1)
        validateContinuation(text, delimiter)
        stream.continuations.push({ kind: delimiter === '"' ? 'intent' : 'cli', value: text })
        stream[delimiter === '"' ? 'intents' : 'cli'].push(text)
        continue
      }
      validateService(payload)
      const verbPrefix = `${glyphs.verb} `
      if (!parts[0]?.startsWith(verbPrefix)) {
        stream.continuations.push(payload)
        continue
      }
      if (payload !== glyphs.service) {
        throw new Error('GESTALT executable action service is not LUCID')
      }
      const semanticAction = { verb: '' }
      parseCoordinate(parts, semanticAction)
      if (!semanticAction.verb) throw new Error('GESTALT action verb is absent')
      const evidencePrefix = `${glyphs.evidence} `
      if (parts[0]?.startsWith(evidencePrefix)) {
        semanticAction.label = semanticValue(parts.shift().slice(evidencePrefix.length))
      }
      stream.actions.push(semanticAction)
      continue
    }
    const relation = [
      ['evidence', glyphs.evidence],
      ['data', glyphs.datum],
      ['timing', glyphs.timing]
    ].find(([, glyph]) => part.startsWith(`${glyph} `))
    if (!relation) {
      if (isTiming(part) && !part.startsWith(`${glyphs.timing} `)) {
        stream.timing.push(semanticValue(part))
        continue
      }
      throw new Error('GESTALT segment is not canonical')
    }
    const [field, glyph] = relation
    stream[field].push(semanticValue(part.slice(glyph.length + 1)))
  }
  return stream
}

function validateService(value) {
  if (
    typeof value !== 'string' ||
    !value ||
    new TextEncoder().encode(value).length > 64 ||
    /^[\x00-\x7f]*$/.test(value) ||
    /[\p{White_Space}\p{Cc}\p{Alphabetic}\p{Number}]/u.test(value) ||
    segments.signals.includes(value) ||
    fields.slice(2).some(field => glyphs[field] === value)
  ) {
    throw new Error('GESTALT service is not a bounded glyph')
  }
  rejectJson(value)
}

function isService(value) {
  try {
    validateService(value)
    return true
  } catch {
    return false
  }
}

function parseCoordinate(parts, target) {
  for (const field of ['verb', 'noun']) {
    const prefix = `${glyphs[field]} `
    if (parts[0]?.startsWith(prefix)) {
      target[field] = asciiLower(parts.shift().slice(prefix.length))
    }
  }
  target.arguments = []
  const prefix = `${glyphs.argument} `
  while (parts[0]?.startsWith(prefix)) target.arguments.push(parts.shift().slice(prefix.length))
  coordinate(target.verb, target.noun, target.arguments)
  if (target.arguments.length === 1) target.argument = target.arguments[0]
}

function arrayField(values) {
  if (values === undefined) return []
  if (!Array.isArray(values)) throw new Error('GESTALT repeated fields require arrays')
  return values
}

function argumentValues(source) {
  const values = arrayField(source.arguments)
  if (source.argument == null) return values
  if (values.length > 0 && (values.length !== 1 || values[0] !== source.argument)) {
    throw new Error('GESTALT argument sources conflict')
  }
  return [source.argument]
}

function coordinate(verb, noun, arguments_) {
  if (verb === '' && noun == null && arguments_.length === 0) return []
  if ((verb == null && (noun != null || arguments_.length > 0)) || (noun == null && arguments_.length > 0)) {
    throw new Error('GESTALT coordinate dependencies are invalid')
  }
  const values = []
  if (verb != null) {
    if (!segments.verbs.includes(verb)) throw new Error('GESTALT verb is not canonical')
    values.push(`${glyphs.verb} ${asciiUpper(verb)}`)
  }
  if (noun != null) values.push(`${glyphs.noun} ${asciiUpper(semanticValue(noun))}`)
  for (const argument of arguments_) {
    const value = semanticValue(argument)
    values.push(`${glyphs.argument} ${/["`]/.test(value) ? value : asciiUpper(value)}`)
  }
  return values
}

function isTiming(value) {
  const boundary = value.indexOf(' ')
  return boundary > 0 && boundary < value.length - 1 && segments.signals.includes(value.slice(0, boundary))
}

function validateContinuation(value, delimiter) {
  if (
    typeof value !== 'string' ||
    !value ||
    new TextEncoder().encode(value).length > 1024 ||
    /\p{Cc}/u.test(value) ||
    value.includes(delimiter)
  ) {
    throw new Error('GESTALT CYOA continuation is invalid')
  }
  rejectJson(value)
}

function renderContinuation(value, delimiter) {
  validateContinuation(value, delimiter)
  return `${glyphs.action} ${delimiter}${value}${delimiter}`
}

function semanticValue(value) {
  if (typeof value !== 'string' || !value) throw new Error('GESTALT semantic value is invalid')
  let normalized = value
  if (/[\r\n]/.test(value)) {
    const parts = []
    let remaining = value
    while (true) {
      const boundary = separatorOutsideLiterals(remaining, ['\r', '\n'])
      if (boundary === undefined) break
      parts.push(remaining.slice(0, boundary), ' ')
      remaining = remaining.slice(boundary + 1)
    }
    parts.push(remaining)
    normalized = parts.join('')
    if (/[\r\n]/.test(normalized)) throw new Error('GESTALT literal requires single-line source')
  }
  rejectJson(normalized)
  if (separatorOutsideLiterals(normalized, [segments.separator]) !== undefined) {
    throw new Error('GESTALT semantic value contains the canonical separator; use separate semantic fields')
  }
  if (separatorOutsideLiterals(normalized, gestaltContract.lint.alternateSeparators) !== undefined) {
    throw new Error('GESTALT semantic value contains an alternate separator; use separate semantic fields')
  }
  return normalized
}

function streamParts(value) {
  if (typeof value !== 'string' || /[\r\n]/.test(value)) {
    throw new Error('GESTALT stream must be one physical line')
  }
  let remaining = value
  const parts = []
  const actionPrefix = `${glyphs.action} `
  while (true) {
    const trimmed = remaining.trimStart()
    const payload = trimmed.startsWith(actionPrefix) ? trimmed.slice(actionPrefix.length) : ''
    let boundary
    if (payload.startsWith('"') || payload.startsWith('`')) {
      const closing = payload.indexOf(payload[0], 1)
      if (closing < 0) throw new Error('GESTALT CYOA quote is unclosed')
      const end = remaining.length - trimmed.length + actionPrefix.length + closing + 1
      const suffix = remaining.slice(end)
      if (suffix.trim()) {
        const separator = suffix.indexOf(segments.separator)
        if (separator < 0 || suffix.slice(0, separator).trim()) {
          throw new Error('GESTALT CYOA has trailing unsegmented text')
        }
        boundary = end + separator
      }
    } else {
      boundary = separatorOutsideLiterals(remaining, [segments.separator])
    }
    if (boundary === undefined) {
      parts.push(remaining.trim())
      return parts
    }
    parts.push(remaining.slice(0, boundary).trim())
    remaining = remaining.slice(boundary + segments.separator.length)
  }
}

function separatorOutsideLiterals(value, separators) {
  let quote
  let quoteRun = 0
  const brackets = []
  let escaped = false
  let offset = 0
  while (offset < value.length) {
    const character = String.fromCodePoint(value.codePointAt(offset))
    let run = 1
    if (character === '`' || character === '$') {
      while (value[offset + run] === character) run += 1
    }
    const next = offset + character.length * run
    if (escaped) {
      escaped = false
    } else if (character === '\\') {
      escaped = true
    } else if (quote !== undefined) {
      if (character === quote && run === quoteRun) quote = undefined
    } else if (character === '$' && run === 1 && (value[next] === '[' || value[next] === '.')) {
      offset = next
      continue
    } else if (
      ['"', '`', '$', '\u201c', '\u2018'].includes(character) ||
      (character === "'" &&
        !(
          /[\p{Alphabetic}\p{Number}]$/u.test(value.slice(0, offset)) &&
          /^[\p{Alphabetic}\p{Number}]/u.test(value.slice(next))
        ))
    ) {
      quote = { '\u201c': '\u201d', '\u2018': '\u2019' }[character] ?? character
      quoteRun = run
    } else if ('([{'.includes(character)) {
      if (brackets.length === gestaltContract.recovery.bounds.nesting) return undefined
      brackets.push({ '(': ')', '[': ']', '{': '}' }[character])
    } else if (')]}'.includes(character)) {
      if (brackets.pop() !== character) return undefined
    } else if (brackets.length === 0 && separators.some(separator => value.startsWith(separator, offset))) {
      return offset
    }
    offset = next
  }
  return undefined
}

function jsonPrefix(value, start) {
  let quoted = false
  let escaped = false
  let depth = 0
  for (let offset = start; offset < value.length; offset += 1) {
    const character = value[offset]
    if (quoted) {
      if (escaped) escaped = false
      else if (character === '\\') escaped = true
      else if (character === '"') quoted = false
    } else if (character === '"') quoted = true
    else if (character === '{' || character === '[') depth += 1
    else if (character === '}' || character === ']') depth -= 1
    if (!quoted && depth === 0) {
      try {
        return JSON.parse(value.slice(start, offset + 1))
      } catch {
        return undefined
      }
    }
  }
  return undefined
}

function rejectJson(value) {
  const pending = [[value, 0]]
  while (pending.length > 0) {
    const [text, depth] = pending.pop()
    if (depth > 32) throw new Error('GESTALT literal nesting exceeds its bound')
    for (let offset = 0; offset < text.length; offset += 1) {
      const character = text[offset]
      if (!'{["'.includes(character)) continue
      if (
        character === '[' &&
        /[\p{Alphabetic}\p{Number}$_.\]]$/u.test(text.slice(0, offset)) &&
        /^\[[0-9]+\]/.test(text.slice(offset))
      )
        continue
      const decoded = jsonPrefix(text, offset)
      if (decoded !== null && typeof decoded === 'object') {
        throw new Error('JSON is transport data, not canonical GESTALT')
      }
      if (typeof decoded === 'string' && decoded.length < text.length) pending.push([decoded, depth + 1])
    }
  }
}
