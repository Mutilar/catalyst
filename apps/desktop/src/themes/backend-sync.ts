/**
 * Live skin sync from the Hermes backend.
 *
 * The backend resolves the active skin (built-in or `$HERMES_HOME/skins/*.yaml`)
 * and announces it on `gateway.ready` / `skin.changed`, and answers `config.get
 * skin` with the same payload. `ingestBackendSkin` folds that into the desktop:
 *
 *   1. Registers the converted theme in `$backendThemes` so it appears wherever a
 *      built-in does — Appearance, Cmd-K, `/skin` — with no per-surface wiring
 *      (`listAllThemes` merges this store).
 *   2. When asked to apply (an explicit change), requests the switch via
 *      `$pendingSkinApply`, which the ThemeProvider drains through `setTheme`.
 *
 * `gateway.ready` seeds the baseline WITHOUT applying, so a fresh connect never
 * stomps the user's persisted desktop theme; only a genuine name change (Hermes
 * authoring/activating a skin from a prompt, or `/skin` elsewhere) repaints.
 */

import type { HermesSkin } from '@hermes/shared/skin'
import { atom } from 'nanostores'

import { BUILTIN_THEMES } from './presets'
import { isUgUiSkinBinding, skinToDesktopTheme, uguiBindingToDesktopTheme } from './skin'
import type { DesktopTheme, ThemeMode } from './types'
import { UGUI_THEMES } from './ugui-skins'

/** Skins pushed by the backend, keyed by name. Merged by `listAllThemes`. */
export const $backendThemes = atom<Record<string, DesktopTheme>>({})

/** One-shot skin name the ThemeProvider should switch to (it clears this). */
export const $pendingSkinApply = atom<string | null>(null)
export const $pendingModeApply = atom<ThemeMode | null>(null)

interface LucidHostAppearance {
  apply?: boolean
  binding?: unknown
  mode?: ThemeMode
  schema?: string
  skin?: string
  skin_name?: string
}

// Last skin name synced from the backend + whether it was ever APPLIED (vs
// merely seeded at connect). Once applied, only a name change applies again —
// no re-apply on repeat events, no snap-back after a manual desktop switch.
// A `skin.changed` matching a seed-only baseline still applies: the seed
// records without painting, so if the activation event was missed (backend
// restart / disconnected), an explicit re-affirm must repaint, not no-op.
let lastSynced: { applied: boolean; name: string } | null = null

/** Test-only: reset the module's apply guard + registry between cases. */
export function __resetBackendSkinSync(): void {
  lastSynced = null
  $backendThemes.set({})
  $pendingSkinApply.set(null)
  $pendingModeApply.set(null)
}

/** Apply one validated LUCID appearance effect through ThemeProvider's persistence seam. */
export function ingestLucidHostAppearance(value: unknown): boolean {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return false
  }

  const effect = value as LucidHostAppearance

  if (effect.schema !== 'lucid-host-appearance/1' || effect.apply !== true) {
    return false
  }

  const mode = effect.mode
  const skin = typeof effect.skin === 'string' ? effect.skin.trim() : ''

  if (mode !== undefined && mode !== 'light' && mode !== 'dark' && mode !== 'system') {
    return false
  }

  if (skin && !/^[a-z0-9][a-z0-9-]{0,63}$/.test(skin)) {
    return false
  }

  if (!mode && !skin) {
    return false
  }

  if (skin && effect.binding !== undefined) {
    if (!isUgUiSkinBinding(effect.binding)) {
      return false
    }

    const theme = uguiBindingToDesktopTheme(skin, effect.skin_name?.trim() || skin, effect.binding)

    if (!theme) {
      return false
    }

    $backendThemes.set({ ...$backendThemes.get(), [skin]: theme })
  }

  if (mode) {
    $pendingModeApply.set(mode)
  }

  if (skin) {
    $pendingSkinApply.set(skin)
  }

  return true
}

/**
 * Fold a resolved skin into the desktop. `apply: false` (connect-time seed) only
 * records the baseline; `apply: true` (runtime change / poll) repaints on a name
 * change. Built-in names keep the desktop's own palette but can still be applied.
 */
export function ingestBackendSkin(skin: HermesSkin | undefined | null, { apply }: { apply: boolean }): void {
  const name = (skin && typeof skin === 'object' ? (skin.name ?? '') : '').trim()

  if (!name) {
    return
  }

  // `default` is "no opinion" on the PALETTE — the desktop keeps its own default
  // (nous), so we never register a converted theme under `default`. It is still a
  // valid apply TARGET though: a runtime switch back to `default` must repaint the
  // desktop to its own default (setTheme normalizes `default` → nous). So we only
  // skip the registry step here and let it flow through the apply logic below.
  // Built-in names (mono/slate/…) already have a hand-tuned desktop palette — we
  // never shadow it, but the name is still a valid apply target.
  if (name !== 'default' && !BUILTIN_THEMES[name] && !UGUI_THEMES[name]) {
    const theme = skinToDesktopTheme(skin as HermesSkin)

    if (!theme) {
      return
    }

    const current = $backendThemes.get()

    if (JSON.stringify(current[name]) !== JSON.stringify(theme)) {
      $backendThemes.set({ ...current, [name]: theme })
    }
  }

  if (!apply) {
    // Connect-time seed: record without painting. A reconnect re-seed keeps an
    // earlier real apply's flag so repeat events can't override a manual switch.
    if (lastSynced?.name !== name || !lastSynced.applied) {
      lastSynced = { applied: false, name }
    }

    return
  }

  if (name !== lastSynced?.name || !lastSynced.applied) {
    lastSynced = { applied: true, name }
    $pendingSkinApply.set(name)
  }
}
