import { extractMcpGestalt, extractMcpUguiDocument, type McpUguiDocument, uguiDocumentIssue } from '@/lib/tool-presentation'

type UguiWasmInitInput = BufferSource | Request | string | URL | WebAssembly.Module

export type UgUiWasmModule = {
  default?: (input?: UguiWasmInitInput | { module_or_path: UguiWasmInitInput }) => Promise<unknown>
  ugui_project_lucid_gestalt?: (gestalt: string) => string
  ugui_project_conversation_text?: (source: string, running: boolean) => string
  ugui_app_load_reference?: (appId: string, source: string, seed: number) => string
  ugui_app_input?: (message: string) => string
  ugui_app_reset?: () => void
  ugui_mount_application_document?: (root: Element, document: string) => string
  projects_project_lucid_gestalt?: (gestalt: string) => string
  catalyst_project_lucid_gestalt?: (gestalt: string) => string
}

export type UguiWasmReader = (assetName: string) => Promise<Uint8Array>

export type ResidentUguiAppDocument = Record<string, unknown> & {
  actions: unknown[]
  header: unknown[]
  id: string
  sections: unknown[]
  type: string
}

let modulePromise: Promise<UgUiWasmModule | null> | null = null
let moduleFailure: string | null = null

export type UguiProjectionResult = {
  document: McpUguiDocument | null
  error: string | null
}

export interface ConversationProjection {
  schema: 'ugui-conversation-text/1'
  source: string
  documents: Array<McpUguiDocument & { source: string; revision: string; streamState: 'pending' | 'complete' }>
}

/** Transport validation only: Rust owns every canonical document and region. */
export async function projectConversationText(source: string, running: boolean): Promise<ConversationProjection> {
  const module = await loadUgUi()
  const project = module?.ugui_project_conversation_text

  if (!project) {
    throw new Error(moduleFailure ?? 'conversation-projector-unavailable')
  }

  return parseConversationProjection(project(source, running), source)
}

/** Validate the transport envelope; never parse or repair conversation content here. */
export function parseConversationProjection(payload: string, source: string): ConversationProjection {
  const refuse = (code: string, path: string, detail: string): never => {
    throw new Error(`conversation-projector-${code}: ${path} ${detail}`)
  }

  const object = (value: unknown, path: string): Record<string, unknown> => {
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
      return refuse('shape-invalid', path, 'expected=object')
    }

    return value as Record<string, unknown>
  }

  let parsed: unknown

  try {
    parsed = JSON.parse(payload)
  } catch {
    return refuse('json-invalid', '/', 'expected=JSON object')
  }

  const value = object(parsed, '/')

  if (value.schema === 'ugui-conversation-text-error/1') {
    const code = typeof value.code === 'string' && /^[a-z0-9-]{1,128}$/.test(value.code)
      ? value.code : 'unrecognized-refusal'

    return refuse('refused', '/code', code)
  }

  if (value.schema !== 'ugui-conversation-text/1') {
    const observed = typeof value.schema === 'string' && /^[a-z0-9._/-]{1,128}$/i.test(value.schema)
      ? value.schema : typeof value.schema

    return refuse('schema-mismatch', '/schema', `expected=ugui-conversation-text/1 observed=${observed}; rebuild matching renderer and WASM through the UGUI factory`)
  }

  if (value.authority !== 'presentation-only') {
    return refuse('authority-invalid', '/authority', 'expected=presentation-only')
  }

  if (value.source !== source) {
    return refuse('source-mismatch', '/source', 'expected=exact request source')
  }

  if (!Array.isArray(value.documents)) {
    return refuse('shape-invalid', '/documents', 'expected=array; rebuild matching renderer and WASM through the UGUI factory')
  }

  for (const [index, candidate] of value.documents.entries()) {
    const path = `/documents/${index}`
    const document = object(candidate, path)
    const issue = uguiDocumentIssue(document)

    if (issue) {
      return refuse(issue.code, `${path}${issue.path}`, issue.detail)
    }

    if (!Array.isArray(document.actions)) {
      return refuse('region-invalid', `${path}/actions`, 'expected=array')
    }

    if (document.authority !== 'presentation-only') {
      return refuse('authority-invalid', `${path}/authority`, 'expected=presentation-only')
    }

    for (const field of ['source', 'revision'] as const) {
      if (typeof document[field] !== 'string') {
        return refuse('metadata-invalid', `${path}/${field}`, 'expected=string')
      }
    }

    if (document.streamState !== 'pending' && document.streamState !== 'complete') {
      return refuse('metadata-invalid', `${path}/streamState`, 'expected=pending or complete')
    }
  }

  if (source.trim() && value.documents.map(document => document.source).join('') !== source) {
    return refuse('source-mismatch', '/documents', 'expected=ordered lossless source partition')
  }

  return value as unknown as ConversationProjection
}

function boundedError(error: unknown): string {
  const detail = error instanceof Error ? error.message : String(error)

  return detail.replace(/[\r\n\t]+/g, ' ').slice(0, 512)
}

export function resolveUguiModuleUrls(baseUrl: string): string[] {
  return ['wasm/ugui_gestalt_wasm.js', 'wasm/catalyst_wasm.js'].map(
    asset => new URL(asset, baseUrl).href
  )
}

export function resolveUguiWasmUrl(moduleUrl: string): string {
  const url = new URL(moduleUrl)

  url.pathname = url.pathname.replace(/\.js$/, '_bg.wasm')

  return url.href
}

export async function initializeUguiModule(
  module: UgUiWasmModule,
  moduleUrl: string,
  readPackagedWasm?: UguiWasmReader
): Promise<UgUiWasmModule> {
  if (module.default) {
    const wasmUrl = resolveUguiWasmUrl(moduleUrl)
    const parsed = new URL(wasmUrl)
    const assetName = parsed.pathname.split('/').pop()

    const input =
      parsed.protocol === 'file:' && assetName && readPackagedWasm
        ? await readPackagedWasm(assetName)
        : wasmUrl

    await module.default({ module_or_path: input })
  }

  return module
}

async function loadUgUi(): Promise<UgUiWasmModule | null> {
  if (!modulePromise) {
    modulePromise = (async () => {
      for (const url of resolveUguiModuleUrls(document.baseURI)) {
        try {
          // wasm-bindgen-cli-support can emit a `web` initializer without a
          // synthesized sibling `_bg.wasm` URL. Bind the exact asset explicitly
          // so Vite HTTP development and packaged Electron resolve identically.
          const module = await initializeUguiModule(
            (await import(/* @vite-ignore */ url)) as UgUiWasmModule,
            url,
            window.hermesDesktop.readUguiWasm
          )

          if (
            module.ugui_project_lucid_gestalt ||
            module.projects_project_lucid_gestalt ||
            module.catalyst_project_lucid_gestalt
          ) {
            moduleFailure = null

            return module
          }

          moduleFailure = `projector-export-missing: ${url}`
        } catch (error) {
          // Keep the legacy façade fallback, but do not make a missing or
          // uninitializable projector observationally identical to a non-UGUI
          // result. This remains renderer-local diagnostic evidence.
          console.warn(`UGUI projector initialization failed for ${url}`, error)
          moduleFailure = `projector-initialization-failed: ${url}: ${boundedError(error)}`
        }
      }

      return null
    })()
  }

  const module = await modulePromise

  if (!module) {
    // A transient build/rollover may briefly remove the staged WASM assets.
    // Do not pin that degradation for the renderer's entire lifetime.
    modulePromise = null
  }

  return module
}

function parseResidentDocument(source: string): ResidentUguiAppDocument {
  const value = JSON.parse(source) as Record<string, unknown>

  if (
    !value ||
    typeof value !== 'object' ||
    typeof value.id !== 'string' ||
    typeof value.type !== 'string' ||
    !Array.isArray(value.header) ||
    !Array.isArray(value.sections) ||
    !Array.isArray(value.actions) ||
    typeof value.error === 'string'
  ) {
    throw new Error(typeof value?.detail === 'string' ? value.detail : 'UGUI app returned an invalid document')
  }

  return value as ResidentUguiAppDocument
}

export async function loadResidentUguiApp(
  appId: string,
  source: string,
  seed: number
): Promise<ResidentUguiAppDocument> {
  const module = await loadUgUi()
  const load = module?.ugui_app_load_reference

  if (!load) {
    throw new Error('The UGUI resident app engine is unavailable')
  }

  return parseResidentDocument(load(appId, source, seed))
}

export async function inputResidentUguiApp(
  message: Record<string, unknown>
): Promise<ResidentUguiAppDocument> {
  const module = await loadUgUi()
  const input = module?.ugui_app_input

  if (!input) {
    throw new Error('The UGUI resident app input seam is unavailable')
  }

  return parseResidentDocument(input(JSON.stringify(message)))
}

export async function mountResidentUguiDocument(
  root: Element,
  document: ResidentUguiAppDocument
): Promise<void> {
  const module = await loadUgUi()
  const mount = module?.ugui_mount_application_document

  if (!mount) {
    throw new Error('The UGUI browser painter is unavailable')
  }

  const receipt = JSON.parse(mount(root, JSON.stringify(document))) as Record<string, unknown>

  if (receipt.mounted !== true) {
    throw new Error(typeof receipt.detail === 'string' ? receipt.detail : 'UGUI browser painter refused the app')
  }
}

export async function resetResidentUguiApp(): Promise<void> {
  const module = await loadUgUi()
  module?.ugui_app_reset?.()
}

/**
 * Thin client seam over the UGUI-owned Gestalt transformer. Catalyst never
 * interprets Gestalt fields, templates, actions, or fidelity itself.
 */
export async function projectMcpGestaltResult(result: unknown): Promise<McpUguiDocument | null> {
  const gestalt = extractMcpGestalt(result)

  if (!gestalt) {
    return null
  }

  return projectLucidGestalt(gestalt)
}

export async function projectLucidGestalt(gestalt: string): Promise<McpUguiDocument | null> {
  return (await projectLucidGestaltDetailed(gestalt)).document
}

export async function projectLucidGestaltDetailed(
  gestalt: string
): Promise<UguiProjectionResult> {
  if (!gestalt.trim()) {
    return { document: null, error: 'gestalt-empty' }
  }

  const module = await loadUgUi()

  const project =
    module?.ugui_project_lucid_gestalt ??
    module?.projects_project_lucid_gestalt ??
    module?.catalyst_project_lucid_gestalt

  if (!project) {
    return { document: null, error: moduleFailure ?? 'resident-projector-unavailable' }
  }

  try {
    const document = JSON.parse(project(gestalt)) as Record<string, unknown>

    if (document.schema === 'lucid-gestalt-projection-error/1') {
      const code = typeof document.code === 'string' ? document.code : 'projector-refused'
      const detail = typeof document.detail === 'string' ? document.detail : 'UGUI refused the GESTALT input'

      return { document: null, error: `${code}: ${detail}` }
    }

    const extracted = extractMcpUguiDocument(document)

    return extracted
      ? { document: extracted, error: null }
      : { document: null, error: 'projector-document-invalid' }
  } catch (error) {
    return { document: null, error: `projector-execution-failed: ${boundedError(error)}` }
  }
}
