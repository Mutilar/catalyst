export const API_FAILURE_SCHEMA = 'catalyst-api-failure/1'

export interface ApiFailureEnvelope {
  schema: typeof API_FAILURE_SCHEMA
  failure: {
    code: string
    detail: string
  }
}

export function isApiConnectionReset(error: unknown): boolean {
  const raw = error instanceof Error ? error.message : String(error ?? '')

  return (error as NodeJS.ErrnoException)?.code === 'ECONNRESET' || raw.toLowerCase().includes('socket hang up')
}

export function shouldRetryApiRequest(error: unknown, method = 'GET', upload = false): boolean {
  return !upload && ['GET', 'HEAD'].includes(method.toUpperCase()) && isApiConnectionReset(error)
}

function boundedErrorDetail(raw: string): string {
  return [...raw]
    .map(character => {
      const codePoint = character.charCodeAt(0)

      return codePoint < 32 || codePoint === 127 ? ' ' : character
    })
    .join('')
    .slice(0, 512)
}

export function apiIpcFailure(error: unknown): ApiFailureEnvelope {
  const raw = error instanceof Error ? error.message : String(error ?? '')

  const reset = isApiConnectionReset(error)

  const code = reset ? 'desktop-api-connection-reset' : 'desktop-api-request-failed'
  const detail = reset ? code : boundedErrorDetail(raw) || code

  return { schema: API_FAILURE_SCHEMA, failure: { code, detail } }
}

export function unwrapApiIpcResult<T>(result: T | ApiFailureEnvelope): T {
  if (
    result &&
    typeof result === 'object' &&
    'schema' in result &&
    result.schema === API_FAILURE_SCHEMA &&
    'failure' in result
  ) {
    const error = new Error(result.failure.detail || result.failure.code)
    error.name = result.failure.code || 'desktop-api-request-failed'
    throw error
  }

  return result as T
}
