import { extractMcpGestalt, extractMcpUguiDocument, type McpUguiDocument } from '@/lib/tool-presentation'

type UgUiWasmModule = {
  default?: (input?: string | URL | Request) => Promise<unknown>
  ugui_project_lucid_gestalt?: (gestalt: string) => string
  ugui_app_load_reference?: (appId: string, source: string, seed: number) => string
  ugui_app_input?: (message: string) => string
  ugui_app_reset?: () => void
  ugui_mount_application_document?: (root: Element, document: string) => string
  projects_project_lucid_gestalt?: (gestalt: string) => string
  catalyst_project_lucid_gestalt?: (gestalt: string) => string
}

export type ResidentUguiAppDocument = Record<string, unknown> & {
  actions: unknown[]
  header: unknown[]
  id: string
  sections: unknown[]
  type: string
}

let modulePromise: Promise<UgUiWasmModule | null> | null = null

export function resolveUguiModuleUrls(baseUrl: string): string[] {
  return ['wasm/ugui_gestalt_wasm.js', 'wasm/catalyst_wasm.js'].map(
    asset => new URL(asset, baseUrl).href
  )
}

async function loadUgUi(): Promise<UgUiWasmModule | null> {
  if (!modulePromise) {
    modulePromise = (async () => {
      for (const url of resolveUguiModuleUrls(document.baseURI)) {
        try {
          const module = (await import(/* @vite-ignore */ url)) as UgUiWasmModule

          if (module.default) {
            await module.default()
          }

          if (
            module.ugui_project_lucid_gestalt ||
            module.projects_project_lucid_gestalt ||
            module.catalyst_project_lucid_gestalt
          ) {
            return module
          }
        } catch {
          // Try the temporary legacy façade before degrading to raw Gestalt.
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
  if (!gestalt.trim()) {
    return null
  }

  const module = await loadUgUi()
  const project =
    module?.ugui_project_lucid_gestalt ??
    module?.projects_project_lucid_gestalt ??
    module?.catalyst_project_lucid_gestalt

  if (!project) {
    return null
  }

  try {
    const document = JSON.parse(project(gestalt))

    return extractMcpUguiDocument(document)
  } catch {
    return null
  }
}
