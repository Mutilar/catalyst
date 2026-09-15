export interface GestaltSemanticAction {
  verb: string
  noun?: string | null
  argument?: string
  arguments?: string[]
  label?: string | null
}

export interface GestaltSemanticContinuation {
  kind: 'service' | 'cli' | 'intent'
  value: string
}

export interface GestaltSemanticStream {
  signal: string
  service?: string | null
  withoutIdentity?: boolean
  verb?: string | null
  noun?: string | null
  argument?: string
  arguments?: string[]
  evidence?: string[]
  data?: string[]
  timing?: string[]
  continuations?: (string | GestaltSemanticContinuation)[]
  intents?: string[]
  cli?: string[]
  actions?: GestaltSemanticAction[]
}

export function canonicalGestaltStream(stream: GestaltSemanticStream): string
export function parseGestaltStream(value: string): GestaltSemanticStream
