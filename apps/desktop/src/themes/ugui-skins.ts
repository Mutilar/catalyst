import { uguiBindingToDesktopTheme } from './skin'
import type { DesktopTheme, UgUiSkinBinding } from './types'

interface UgUiSkinDocument {
  binding: UgUiSkinBinding
  id: string
  name: string
}

const modules = import.meta.glob<UgUiSkinDocument>('../../../../../genui/ugui/skins/bindings/*.json', {
  eager: true,
  import: 'default'
})

/** Every generated UGUI binding, bundled from the canonical skin catalog. */
const entries: Array<[string, DesktopTheme]> = []

for (const document of Object.values(modules)) {
  const theme = uguiBindingToDesktopTheme(document.id, document.name, document.binding)

  if (theme) {
    entries.push([theme.name, theme])
  }
}

export const UGUI_THEMES: Record<string, DesktopTheme> = Object.fromEntries(entries)
