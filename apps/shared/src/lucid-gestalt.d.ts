export interface GestaltSemanticAction {
  verb: string
  noun?: string
  argument?: string
  label?: string
}

export interface GestaltSemanticStream {
  signal: string
  service?: string
  verb?: string
  noun?: string
  argument?: string
  evidence?: string[]
  data?: string[]
  timing?: string[]
  continuations?: string[]
  actions?: GestaltSemanticAction[]
}

export function canonicalGestaltStream(stream: GestaltSemanticStream): string
export function parseGestaltStream(value: string): GestaltSemanticStream
