/**
 * Hermes skin → DesktopTheme converter.
 *
 * A "skin" is the CLI/TUI theme unit: a YAML file in `$HERMES_HOME/skins/` (or a
 * built-in) resolved by `hermes_cli/skin_engine.py` and pushed to every surface
 * over JSON-RPC (`gateway.ready`, `skin.changed`, `config.get skin`). This is the
 * one place the desktop turns that CLI-shaped palette into a `DesktopTheme`, so a
 * skin Hermes authors from a prompt lights up all three surfaces from one file.
 *
 * Legacy Hermes skins carry terminal-oriented keys and use the bounded palette
 * derivation below. Canonical UGUI skins carry a complete eight-slot StyleModel
 * binding and use `uguiBindingToDesktopTheme` without dropping structural tokens.
 */

import type { HermesSkin, SkinColors } from '@hermes/shared/skin'

import { ensureContrast, luminance, mix, normalizeHex, readableOn, rgbToHex } from './color'
import type { DesktopTheme, DesktopThemeColors, UgUiSkinBinding } from './types'

// The accent labels the sidebar in small uppercase text, so it must clear WCAG AA
// for normal text or section headers go invisible — mirrors the VS Code importer.
const ACCENT_MIN_CONTRAST = 4.5

const UGUI_STYLE_SLOTS = [
  'palette',
  'typography',
  'geometry',
  'border-model',
  'elevation',
  'density',
  'motion',
  'chrome'
] as const

export function isUgUiSkinBinding(value: unknown): value is UgUiSkinBinding {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return false
  }

  const binding = value as Record<string, unknown>

  if (
    Object.keys(binding).length !== UGUI_STYLE_SLOTS.length ||
    !UGUI_STYLE_SLOTS.every(slot => {
      const tokens = binding[slot]

      return (
        !!tokens &&
        typeof tokens === 'object' &&
        !Array.isArray(tokens) &&
        Object.keys(tokens).length <= 32 &&
        Object.values(tokens).every(token => typeof token === 'string' && token.length <= 512)
      )
    })
  ) {
    return false
  }

  return true
}

const safeCssColor = (value: string | undefined, fallback: string): string => {
  const candidate = value?.trim() ?? ''

  return /^(?:#[0-9a-f]{3,8}|rgba?\([0-9.,%\s]+\))$/i.test(candidate) ? candidate : fallback
}

const flatCssColor = (value: string, backdrop: string): string => {
  const normalized = normalizeHex(value, backdrop)

  if (normalized) {
    return normalized
  }

  const match = value.match(/^rgba?\(\s*([0-9.]+)[,\s]+([0-9.]+)[,\s]+([0-9.]+)(?:\s*[,/]\s*([0-9.]+)(%)?)?\s*\)$/i)

  if (!match) {
    return backdrop
  }

  const rgb = rgbToHex([
    Math.min(255, Number(match[1])),
    Math.min(255, Number(match[2])),
    Math.min(255, Number(match[3]))
  ])

  const alpha = match[4] === undefined ? 1 : Math.min(1, Number(match[4]) / (match[5] ? 100 : 1))

  return mix(backdrop, rgb, alpha)
}

/** First normalizable hex among `keys`, alpha flattened over `backdrop`. */
const pick = (colors: SkinColors, keys: string[], backdrop: string): string | null => {
  for (const key of keys) {
    const value = normalizeHex(colors[key], backdrop)

    if (value) {
      return value
    }
  }

  return null
}

const titleCase = (name: string): string => name.charAt(0).toUpperCase() + name.slice(1)

/**
 * Convert a resolved skin into a `DesktopTheme`, or null when it carries no
 * usable colors (so a broken/empty skin never registers junk).
 */
export function skinToDesktopTheme(skin: HermesSkin): DesktopTheme | null {
  const name = (skin.name ?? '').trim()
  const colors = skin.colors

  if (name && skin.binding) {
    return uguiBindingToDesktopTheme(name, titleCase(name), skin.binding)
  }

  if (!name || !colors || typeof colors !== 'object') {
    return null
  }

  // Background is the backdrop every other token flattens alpha over. Skins are
  // terminal-first so most only tint chrome — `status_bar_bg` is the closest
  // thing to an app surface; `background` is the explicit opt-in for GUI authors.
  const seededBg = pick(colors, ['background', 'status_bar_bg'], '#000000')
  const foregroundSeed = pick(colors, ['ui_text', 'banner_text', 'status_bar_text'], seededBg ?? '#000000')

  // No background given: bucket by foreground luminance (light text ⇒ dark app).
  const background = seededBg ?? (foregroundSeed && luminance(foregroundSeed) > 0.5 ? '#141414' : '#f7f7f8')
  const dark = luminance(background) < 0.4
  const foreground = foregroundSeed ?? (dark ? '#e6e6e6' : '#161616')

  const accentSeed =
    pick(colors, ['ui_accent', 'banner_accent', 'banner_title'], background) ?? mix(foreground, background, 0.55)

  const sidebar = mix(background, foreground, dark ? 0.02 : 0.012)
  const accent = ensureContrast(accentSeed, sidebar, ACCENT_MIN_CONTRAST)

  const border =
    pick(colors, ['ui_border', 'banner_border'], background) ?? mix(background, foreground, dark ? 0.16 : 0.14)

  const mutedForeground =
    pick(colors, ['banner_dim', 'session_border'], background) ?? mix(foreground, background, 0.45)

  const destructive = pick(colors, ['ui_error'], background) ?? '#e25563'

  const palette: DesktopThemeColors = {
    background,
    foreground,
    card: mix(background, foreground, dark ? 0.04 : 0.025),
    cardForeground: foreground,
    muted: mix(background, foreground, dark ? 0.06 : 0.04),
    mutedForeground,
    popover: mix(background, foreground, dark ? 0.08 : 0.05),
    popoverForeground: foreground,
    primary: accent,
    primaryForeground: readableOn(accent),
    secondary: mix(accent, background, dark ? 0.72 : 0.86),
    secondaryForeground: foreground,
    accent: mix(accent, background, dark ? 0.82 : 0.88),
    accentForeground: foreground,
    border,
    input: pick(colors, ['completion_menu_bg'], background) ?? mix(background, foreground, dark ? 0.1 : 0.06),
    ring: accent,
    midground: accent,
    midgroundForeground: readableOn(accent),
    composerRing: accent,
    destructive,
    destructiveForeground: readableOn(destructive),
    sidebarBackground: sidebar,
    sidebarBorder: border,
    userBubble: mix(background, accent, dark ? 0.18 : 0.12),
    userBubbleBorder: border
  }

  return {
    name,
    label: titleCase(name),
    description: 'Hermes skin',
    // Single palette in both slots: a skin is one-mode, so the light/dark toggle
    // shouldn't invert it. renderedModeFor still paints `.dark` from luminance.
    colors: palette,
    darkColors: palette
  }
}

/** Convert one generated UGUI StyleModel binding without dropping non-color slots. */
export function uguiBindingToDesktopTheme(id: string, label: string, binding: UgUiSkinBinding): DesktopTheme | null {
  const palette = binding.palette
  const surface = safeCssColor(palette.surface, '')
  const surfaceFlat = flatCssColor(surface, '#ffffff')
  const foreground = safeCssColor(palette['on-surface'], '')
  const foregroundFlat = flatCssColor(foreground, surfaceFlat)

  if (!id || !surface || !foreground) {
    return null
  }

  const primary = safeCssColor(palette.primary ?? palette.accent, foreground)
  const primaryFlat = flatCssColor(primary, surfaceFlat)
  const accent = safeCssColor(palette.accent ?? palette.primary, primary)
  const accentFlat = flatCssColor(accent, surfaceFlat)
  const border = safeCssColor(palette.border, mix(surfaceFlat, foregroundFlat, 0.2))
  const destructive = safeCssColor(palette.danger, '#c42b1c')
  const disabled = safeCssColor(palette.disabled, mix(foregroundFlat, surfaceFlat, 0.55))
  const dark = luminance(surfaceFlat) < 0.4

  const colors: DesktopThemeColors = {
    background: surface,
    foreground,
    card: surface,
    cardForeground: foreground,
    muted: mix(surfaceFlat, foregroundFlat, dark ? 0.08 : 0.06),
    mutedForeground: disabled,
    popover: surface,
    popoverForeground: foreground,
    primary,
    primaryForeground: readableOn(primaryFlat),
    secondary: mix(accentFlat, surfaceFlat, dark ? 0.7 : 0.82),
    secondaryForeground: foreground,
    accent: mix(accentFlat, surfaceFlat, dark ? 0.76 : 0.86),
    accentForeground: foreground,
    border,
    input: mix(surfaceFlat, foregroundFlat, dark ? 0.12 : 0.08),
    ring: accent,
    midground: accent,
    midgroundForeground: readableOn(accentFlat),
    composerRing: accent,
    destructive,
    destructiveForeground: readableOn(flatCssColor(destructive, surfaceFlat)),
    sidebarBackground: surface,
    sidebarBorder: border,
    userBubble: mix(surfaceFlat, accentFlat, dark ? 0.2 : 0.12),
    userBubbleBorder: border
  }

  const family = binding.typography['family-stack']

  return {
    name: id,
    label,
    description: 'UGUI StyleModel skin',
    colors,
    typography: family ? { fontSans: family, fontMono: family } : undefined,
    skinBinding: binding,
    fixedMode: dark ? 'dark' : 'light'
  }
}
