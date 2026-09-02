import gestaltContract from '../../../../envelope/GESTALT.json'

const segments = gestaltContract.segments

export function canonicalGestaltStream(stream) {
  if (!segments.signals.includes(stream.signal)) {
    throw new Error('GESTALT signal is not canonical')
  }
  const {
    service: defaultService,
    verb: verbGlyph,
    noun: nounGlyph,
    argument: argumentGlyph,
    evidence,
    datum,
    timing,
    action
  } = segments.glyphs
  if (
    ![segments.separator, defaultService, verbGlyph, nounGlyph, argumentGlyph, evidence, datum, timing, action].every(
      Boolean
    )
  ) {
    throw new Error('GESTALT segment contract is invalid')
  }
  if (segments.required.join() !== 'signal' || segments.order.join() !== ['signal', ...segments.optional].join()) {
    throw new Error('GESTALT segment order is invalid')
  }
  if ((!stream.verb && (stream.noun || stream.argument)) || (!stream.noun && stream.argument)) {
    throw new Error('GESTALT coordinate dependencies are invalid')
  }
  const service = stream.service ?? defaultService
  validateService(service)
  const values = [stream.signal, service]
  if (stream.verb) values.push(`${verbGlyph} ${stream.verb.toUpperCase()}`)
  if (stream.noun) values.push(`${nounGlyph} ${stream.noun.toUpperCase()}`)
  if (stream.argument) {
    values.push(`${argumentGlyph} ${/^["[{]/.test(stream.argument) ? stream.argument : stream.argument.toUpperCase()}`)
  }
  for (const [glyph, entries] of [
    [evidence, stream.evidence],
    [datum, stream.data]
  ]) {
    for (const entry of entries ?? []) values.push(`${glyph} ${semanticValue(entry)}`)
  }
  for (const entry of stream.timing ?? []) {
    const value = semanticValue(entry)
    const [timingSignal, ...timingValue] = value.split(' ')
    values.push(
      segments.signals.includes(timingSignal) && timingSignal !== timing && timingValue.length > 0
        ? value
        : `${timing} ${value}`
    )
  }
  for (const continuation of stream.continuations ?? []) {
    validateService(continuation)
    values.push(`${action} ${continuation}`)
  }
  for (const edge of stream.actions ?? []) {
    if (!edge.verb || (!edge.noun && edge.argument)) {
      throw new Error('GESTALT action coordinate is invalid')
    }
    values.push(`${action} ${defaultService}`, `${verbGlyph} ${edge.verb.toUpperCase()}`)
    if (edge.noun) values.push(`${nounGlyph} ${edge.noun.toUpperCase()}`)
    if (edge.argument) values.push(`${argumentGlyph} ${edge.argument}`)
    if (edge.label) values.push(`${evidence} ${semanticValue(edge.label)}`)
  }
  return values.join(segments.separator)
}

export function parseGestaltStream(value) {
  if (!value || /[\r\n\0]/.test(value)) {
    throw new Error('GESTALT stream must be one nonempty logical line')
  }
  const parts = value.split(segments.separator).map(part => part.trim())
  const signal = parts.shift()
  if (!signal || !segments.signals.includes(signal)) throw new Error('GESTALT signal is invalid')
  const service = isService(parts[0]) ? parts.shift() : undefined
  const stream = { signal, service, evidence: [], data: [], timing: [], continuations: [], actions: [] }
  parseCoordinate(parts, stream)
  while (parts.length > 0) {
    const part = parts.shift()
    const actionPrefix = `${segments.glyphs.action} `
    if (part.startsWith(actionPrefix) && isService(part.slice(actionPrefix.length))) {
      const actionService = part.slice(actionPrefix.length)
      const verbPrefix = `${segments.glyphs.verb} `
      if (!parts[0]?.startsWith(verbPrefix)) {
        stream.continuations.push(actionService)
        continue
      }
      if (actionService !== segments.glyphs.service) {
        throw new Error('GESTALT executable action service is not LUCID')
      }
      const semanticAction = { verb: '' }
      parseCoordinate(parts, semanticAction)
      if (!semanticAction.verb) throw new Error('GESTALT action verb is absent')
      const evidencePrefix = `${segments.glyphs.evidence} `
      if (parts[0]?.startsWith(evidencePrefix)) semanticAction.label = parts.shift().slice(evidencePrefix.length)
      stream.actions.push(semanticAction)
      continue
    }
    const relation = [
      ['evidence', segments.glyphs.evidence],
      ['data', segments.glyphs.datum],
      ['timing', segments.glyphs.timing]
    ].find(([, glyph]) => part.startsWith(`${glyph} `))
    if (!relation) {
      const [timingSignal, ...timingValue] = part.split(' ')
      if (
        segments.signals.includes(timingSignal) &&
        timingSignal !== segments.glyphs.timing &&
        timingValue.length > 0
      ) {
        stream.timing.push(part)
        continue
      }
      throw new Error('GESTALT segment is not canonical')
    }
    const [field, glyph] = relation
    stream[field].push(part.slice(glyph.length + 1))
  }
  return stream
}

function validateService(value) {
  if (!value || new TextEncoder().encode(value).length > 64 || /[\s\x00-\x7f]/u.test(value)) {
    throw new Error('GESTALT service is not a bounded glyph')
  }
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
  for (const field of ['verb', 'noun', 'argument']) {
    const prefix = `${segments.glyphs[field]} `
    if (parts[0]?.startsWith(prefix)) {
      const value = parts.shift().slice(prefix.length)
      target[field] = field === 'argument' ? value : value.toLowerCase()
    }
  }
  if (target.noun && !target.verb) throw new Error('GESTALT noun requires a verb')
  if (target.argument && !target.noun) throw new Error('GESTALT argument requires a noun')
}

function semanticValue(value) {
  if (!value) throw new Error('GESTALT semantic value is invalid')
  return value.replace(/[\r\n]/g, ' ').replaceAll(segments.separator, ' / ')
}
