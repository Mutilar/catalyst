import { extractMcpGestalt, extractMcpUguiDocument, type McpUguiDocument } from '@/lib/tool-presentation'

type UgUiWasmModule = {
  default?: (input?: string | URL | Request) => Promise<unknown>
  ugui_project_lucid_gestalt?: (gestalt: string) => string
  projects_project_lucid_gestalt?: (gestalt: string) => string
  catalyst_project_lucid_gestalt?: (gestalt: string) => string
}

let modulePromise: Promise<UgUiWasmModule | null> | null = null

async function loadUgUi(): Promise<UgUiWasmModule | null> {
  if (!modulePromise) {
    modulePromise = (async () => {
      for (const url of ['/wasm/ugui_gestalt_wasm.js', '/wasm/catalyst_wasm.js']) {
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

  return modulePromise
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
