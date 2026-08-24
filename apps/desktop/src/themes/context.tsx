/**
 * Desktop theme context.
 *
 * Applies the active theme as CSS custom properties on :root so every
 * Tailwind utility that references a color or font-family token picks up
 * the change automatically.
 *
 * Mode (light/dark/system) controls brightness; skin controls accent.
 * The two are persisted independently. Shift+X toggles light/dark.
 */

import { useStore } from '@nanostores/react'
import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useState } from 'react'

import { $registryVersion } from '@/contrib/registry'
import { matchesQuery, useMediaQuery } from '@/hooks/use-media-query'
import { persistString, persistStringRecord, storedString, storedStringRecord } from '@/lib/storage'
import { $activeGatewayProfile, normalizeProfileKey } from '@/store/profile'

import { $backendThemes, $pendingModeApply, $pendingSkinApply } from './backend-sync'
import { hexToRgb, mix, normalizeHex, readableOn } from './color'
import { BUILTIN_THEME_LIST, DEFAULT_SKIN_NAME, DEFAULT_TYPOGRAPHY, nousTheme } from './presets'
import type { DesktopTheme, DesktopThemeColors, ThemeMode, UgUiSkinBinding } from './types'
import { $userThemes, listAllThemes, resolveTheme } from './user-themes'

// Legacy global skin (pre per-profile themes). Still the inheritance fallback
// for any profile without its own assignment, so single-profile users and old
// installs are unaffected.
const SKIN_KEY = 'hermes-desktop-theme-v2'
const MODE_KEY = 'hermes-desktop-mode-v1'
// Per-profile skin + light/dark mode assignments: { [profileKey]: value }. A
// profile inherits the global default until it's given its own appearance.
const PROFILE_SKINS_KEY = 'hermes-desktop-profile-themes-v1'
const PROFILE_MODES_KEY = 'hermes-desktop-profile-modes-v1'
// Last active profile, recorded so the boot-time paint can pick that profile's
// theme before the gateway reports which profile actually launched.
const LAST_PROFILE_KEY = 'hermes-desktop-active-profile-v1'
const RETIRED_SKINS = new Set(['nous-light', 'default', 'gold'])

export type { ThemeMode } from './types'

const INJECTED_FONT_URLS = new Set<string>()

const resolveMode = (mode: ThemeMode, systemDark = matchesQuery('(prefers-color-scheme: dark)')): 'light' | 'dark' =>
  mode === 'system' ? (systemDark ? 'dark' : 'light') : mode

const normalizeSkin = (name: string | null): string =>
  name && resolveTheme(name) && !RETIRED_SKINS.has(name) ? name : DEFAULT_SKIN_NAME

const normalizeMode = (value: string | null): ThemeMode =>
  value === 'light' || value === 'dark' || value === 'system' ? value : 'light'

// ─── Per-profile appearance persistence ─────────────────────────────────────
// Skin and mode are each stored per profile. "default" isn't a real profile —
// it *is* the legacy global slot, so it reads/writes the global directly. Named
// profiles get their own entry and fall back to that global until assigned, so
// unassigned profiles and pre-per-profile installs stay on the global value.
const profilePref = <T extends string>(record: string, legacy: string, normalize: (v: string | null) => T) => ({
  resolve: (profile: string): T => normalize(storedStringRecord(record)[profile] ?? storedString(legacy)),
  assign: (profile: string, value: T): void => {
    if (profile === 'default') {
      persistString(legacy, value)
    } else {
      persistStringRecord(record, { ...storedStringRecord(record), [profile]: value })
    }
  }
})

export const skinPref = profilePref(PROFILE_SKINS_KEY, SKIN_KEY, normalizeSkin)
export const modePref = profilePref(PROFILE_MODES_KEY, MODE_KEY, normalizeMode)

// Last active profile — lets the boot paint pick its appearance before the
// gateway reports which profile actually launched.
const readBootProfileKey = () => normalizeProfileKey(storedString(LAST_PROFILE_KEY))
const rememberActiveProfileKey = (profile: string) => persistString(LAST_PROFILE_KEY, profile)

// ─── Color math (for synthesised light variants of dark-only skins) ────────
// hexToRgb / mix / readableOn live in ./color so the VS Code converter shares
// the exact same math.

function synthLightColors(seed: DesktopTheme): DesktopThemeColors {
  const accent = seed.colors.ring || seed.colors.primary
  const soft = mix('#ffffff', accent, 0.1)
  const softer = mix('#ffffff', accent, 0.06)
  const border = mix('#ececef', accent, 0.14)
  const midground = seed.colors.midground ?? accent

  return {
    background: '#ffffff',
    foreground: '#161616',
    card: '#ffffff',
    cardForeground: '#161616',
    muted: softer,
    mutedForeground: mix('#6b6b70', accent, 0.16),
    popover: '#ffffff',
    popoverForeground: '#161616',
    primary: accent,
    primaryForeground: readableOn(accent),
    secondary: soft,
    secondaryForeground: mix('#2a2a2a', accent, 0.34),
    accent: soft,
    accentForeground: mix('#2a2a2a', accent, 0.34),
    border,
    input: mix('#e2e2e6', accent, 0.18),
    ring: accent,
    midground,
    midgroundForeground: readableOn(midground),
    destructive: '#b94a3a',
    destructiveForeground: '#ffffff',
    sidebarBackground: mix('#fafafa', accent, 0.05),
    sidebarBorder: border,
    userBubble: soft,
    userBubbleBorder: border
  }
}

/** Returns the seed palette for a given skin + mode (no overrides applied). */
export function getBaseColors(skinName: string, mode: 'light' | 'dark'): DesktopThemeColors {
  const seed = resolveTheme(skinName) ?? nousTheme

  if (seed.fixedMode) {
    return seed.colors
  }

  if (mode === 'dark') {
    return seed.darkColors ?? seed.colors
  }

  return seed.darkColors ? seed.colors : synthLightColors(seed)
}

function deriveTheme(skinName: string, mode: 'light' | 'dark'): DesktopTheme {
  const seed = resolveTheme(skinName) ?? nousTheme

  return {
    ...seed,
    name: `${skinName}-${mode}`,
    label: `${seed.label} ${mode === 'light' ? 'Light' : 'Dark'}`,
    description: `${seed.label} ${mode} palette`,
    colors: getBaseColors(skinName, mode)
  }
}

/**
 * Some palettes intentionally keep a bright background even when
 * `mode === 'dark'`, so we shouldn't apply the `.dark` class. Decide from
 * the actual background luminance.
 */
function renderedModeFor(colors: DesktopThemeColors, mode: 'light' | 'dark'): 'light' | 'dark' {
  const rgb = hexToRgb(colors.background)

  if (!rgb) {
    return mode
  }

  const [r, g, b] = rgb.map(v => v / 255)

  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.5 ? 'light' : 'dark'
}

// ─── CSS application ────────────────────────────────────────────────────────

// Per-mode mix knobs. Light/dark fallbacks live in styles.css `:root` /
// `:root.dark`; setting them inline keeps active-skin overrides surviving
// the boot-time paint.
// styles.css --theme-neutral-chrome — keep in sync.
const NEUTRAL_CHROME = { light: '#f3f3f3', dark: '#0d0d0e' } as const

const chromeBackground = (background: string, isDark: boolean) =>
  mix(background, NEUTRAL_CHROME[isDark ? 'dark' : 'light'], isDark ? 0.26 : 0.08)

const mixesFor = (isDark: boolean): Record<string, string> => ({
  '--theme-mix-chrome': isDark ? '74%' : '92%',
  '--theme-mix-sidebar': '100%',
  '--theme-mix-card': isDark ? '38%' : '22%',
  '--theme-mix-elevated': isDark ? '46%' : '28%',
  '--theme-mix-bubble': isDark ? '46%' : '0%'
})

const SKIN_STYLE_SLOTS: Array<keyof UgUiSkinBinding> = [
  'palette',
  'typography',
  'geometry',
  'border-model',
  'elevation',
  'density',
  'motion',
  'chrome'
]

const descriptorValue = (value: string | undefined, key: string): string | undefined =>
  value
    ?.split(';')
    .map(part => part.trim())
    .find(part => part.startsWith(`${key}:`))
    ?.slice(key.length + 1)

function applySkinBinding(root: HTMLElement, binding: UgUiSkinBinding | undefined): void {
  for (const property of Array.from(root.style)) {
    if (property.startsWith('--skin-')) {
      root.style.removeProperty(property)
    }
  }
  delete root.dataset.hermesBorderModel
  delete root.dataset.hermesMotion
  for (const property of [
    '--radius-scalar',
    '--dt-spacing-mul',
    '--titlebar-height',
    '--conversation-caption-font-size',
    '--conversation-text-font-size'
  ]) {
    root.style.removeProperty(property)
  }

  if (!binding) {
    return
  }

  for (const slot of SKIN_STYLE_SLOTS) {
    for (const [token, value] of Object.entries(binding[slot] ?? {})) {
      root.style.setProperty(`--skin-${slot}-${token}`, value)
    }
  }
  const desktopBackground = binding.chrome['desktop-background']
  if (desktopBackground?.startsWith('url("/png/backgrounds/')) {
    root.style.setProperty(
      '--skin-chrome-desktop-background',
      desktopBackground.replace('url("/png/backgrounds/', 'url("./png/backgrounds/')
    )
  }

  const radii = binding.geometry['radius-scale']?.split('/').map(value => value.trim()) ?? []
  const radius = radii[Math.min(1, radii.length - 1)]
  const radiusPx = Number.parseFloat(radius ?? '')
  if (Number.isFinite(radiusPx)) {
    root.style.setProperty('--radius-scalar', String(radiusPx / 12))
  }
  if (radius) {
    root.style.setProperty('--skin-radius', radius)
  }
  const strokeWidth = binding.geometry['stroke-width']?.split('/')[0]?.trim()
  if (strokeWidth) {
    root.style.setProperty('--skin-stroke-width', strokeWidth)
  }
  const gridPx = Number.parseFloat(binding.geometry['grid-unit'] ?? '')
  if (Number.isFinite(gridPx)) {
    root.style.setProperty('--dt-spacing-mul', String(gridPx / 8))
  }
  const spacing = binding.density['spacing-scale']?.split('/')[0]?.trim()
  if (spacing) {
    root.style.setProperty('--skin-spacing', spacing)
  }
  const typeScale = binding.typography['scale-ramp']?.split('/').map(value => value.trim()) ?? []
  if (typeScale[0]) {
    root.style.setProperty('--conversation-caption-font-size', typeScale[0])
  }
  if (typeScale[1]) {
    root.style.setProperty('--conversation-text-font-size', typeScale[1])
  }
  if (binding.typography.tracking) {
    root.style.setProperty('--skin-letter-spacing', binding.typography.tracking.split('/')[0].trim())
  }
  if (binding.typography.case) {
    root.style.setProperty('--skin-text-transform', binding.typography.case)
  }
  for (const [token, property] of [
    ['control-height', '--skin-control-height'],
    ['hit-target', '--skin-hit-target']
  ] as const) {
    const value = binding.density[token]
    if (value) {
      root.style.setProperty(property, value)
    }
  }
  const titlebarHeight = descriptorValue(binding.chrome['title-bar'], 'height')
  if (titlebarHeight) {
    root.style.setProperty('--titlebar-height', titlebarHeight)
  }
  const scrollbarWidth = descriptorValue(binding.chrome.scrollbar, 'width')
  if (scrollbarWidth) {
    root.style.setProperty('--skin-scrollbar-width', scrollbarWidth)
  }
  const duration = binding.motion.none ?? binding.motion['duration-ramp']?.split('/')[0]?.trim()
  if (duration) {
    root.style.setProperty('--skin-motion-duration', duration)
  }
  const easing = binding.motion['easing-set']?.split(';')[0]?.split(':').at(-1)?.trim()
  if (easing) {
    root.style.setProperty('--skin-motion-easing', easing)
  }
  const raisedColors = binding['border-model']['raised-delta']?.match(/#[0-9a-f]{6,8}/gi) ?? []
  const sunkenColors = binding['border-model']['sunken-delta']?.match(/#[0-9a-f]{6,8}/gi) ?? []
  if (raisedColors[0]) root.style.setProperty('--skin-raised-light', raisedColors[0])
  if (raisedColors[1]) root.style.setProperty('--skin-raised-dark', raisedColors[1])
  if (sunkenColors[0]) root.style.setProperty('--skin-sunken-dark', sunkenColors[0])
  if (sunkenColors[1]) root.style.setProperty('--skin-sunken-light', sunkenColors[1])
  const shadow = binding.elevation['dual-shadow']
  if (shadow) {
    root.style.setProperty('--skin-elevation-shadow', shadow)
  }
  const outline = binding['border-model'].outline
  if (outline) {
    root.style.setProperty('--skin-outline', outline)
  }
  if (binding['border-model'].bevel) {
    root.dataset.hermesBorderModel = 'bevel'
  } else if (binding['border-model'].outline || binding['border-model'].flat) {
    root.dataset.hermesBorderModel = 'flat'
  }
  root.dataset.hermesMotion = binding.motion.none !== undefined ? 'none' : 'animated'
}

function applyTheme(theme: DesktopTheme, mode: 'light' | 'dark') {
  if (typeof document === 'undefined') {
    return
  }

  const root = document.documentElement
  const c = theme.colors
  const typo = { ...DEFAULT_TYPOGRAPHY, ...nousTheme.typography, ...theme.typography }
  const rendered = renderedModeFor(c, mode)
  const isDark = rendered === 'dark'
  const midground = c.midground ?? c.ring
  const skinName = theme.name.endsWith(`-${mode}`) ? theme.name.slice(0, -mode.length - 1) : theme.name

  root.style.setProperty('color-scheme', rendered)
  root.dataset.hermesTheme = skinName
  root.dataset.hermesMode = rendered
  root.classList.toggle('dark', isDark)
  applySkinBinding(root, theme.skinBinding)

  // Brand seeds feed every glass + shadcn token via `color-mix()` in styles.css.
  const seeds: Record<string, string> = {
    '--theme-foreground': c.foreground,
    '--theme-primary': c.primary,
    '--theme-secondary': c.secondary,
    '--theme-accent-soft': c.accent,
    '--theme-midground': midground,
    '--theme-warm': c.primary,
    '--theme-background-seed': c.background,
    '--theme-sidebar-seed': c.sidebarBackground ?? c.background,
    '--theme-card-seed': c.card,
    '--theme-elevated-seed': c.popover,
    '--theme-bubble-seed': c.userBubble ?? c.popover
  }

  // shadcn/Tailwind tokens that aren't derived from the seed chain.
  const palette: Record<string, string> = {
    '--dt-primary-foreground': c.primaryForeground,
    '--dt-secondary-foreground': c.secondaryForeground,
    '--dt-accent-foreground': c.accentForeground,
    '--dt-border': c.border,
    '--dt-input': c.input,
    '--dt-ring': c.ring,
    '--dt-muted': c.muted,
    '--dt-midground-foreground': c.midgroundForeground ?? readableOn(midground),
    '--dt-composer-ring': c.composerRing ?? midground,
    '--dt-destructive': c.destructive,
    '--dt-destructive-foreground': c.destructiveForeground,
    '--dt-sidebar-border': c.sidebarBorder ?? c.border,
    '--dt-user-bubble-border': c.userBubbleBorder ?? c.border,
    '--dt-font-sans': typo.fontSans,
    '--dt-font-mono': typo.fontMono,
    '--noise-opacity-mul': isDark ? 'calc(0.04 / 0.21)' : 'calc(0.34 / 0.21)'
  }

  for (const [k, v] of Object.entries({ ...seeds, ...mixesFor(isDark), ...palette })) {
    root.style.setProperty(k, v)
  }

  const authoredTitlebar = normalizeHex(theme.skinBinding?.palette.titlebar, c.background)
  const authoredTitlebarText = normalizeHex(
    descriptorValue(theme.skinBinding?.chrome['title-bar'], 'color'),
    authoredTitlebar ?? c.background
  )
  const chromeBg = authoredTitlebar ?? chromeBackground(c.background, isDark)

  window.hermesDesktop?.setTitleBarTheme?.({
    background: chromeBg,
    foreground: authoredTitlebarText ?? c.foreground
  })

  // Raw (non-JSON) keys read by the inline pre-paint script in index.html —
  // they let a brand-new window paint the themed background on its very first
  // frame, before this module has even loaded.
  try {
    window.localStorage.setItem('hermes-boot-background', chromeBg)
    window.localStorage.setItem('hermes-boot-color-scheme', rendered)
  } catch {
    // Storage may be unavailable (private mode / quota); the inline script
    // falls back to prefers-color-scheme.
  }

  if (typo.fontUrl && !INJECTED_FONT_URLS.has(typo.fontUrl)) {
    const link = document.createElement('link')
    link.rel = 'stylesheet'
    link.href = typo.fontUrl
    link.dataset.hermesThemeFont = 'true'
    document.head.appendChild(link)
    INJECTED_FONT_URLS.add(typo.fontUrl)
  }
}

// Pin Electron's nativeTheme to the app's mode so the NATIVE window chrome
// (macOS vibrancy material, titlebar, pre-paint background) matches the app
// theme instead of the OS appearance. An explicit light/dark pick is forced;
// 'system' stays 'system' so prefers-color-scheme keeps tracking the OS.
const syncNativeTheme = (pref: ThemeMode, rendered: 'light' | 'dark') =>
  window.hermesDesktop?.setNativeTheme?.(pref === 'system' ? 'system' : rendered)

// Boot-time paint to avoid a flash before <ThemeProvider> mounts. Use the last
// active profile's appearance so a non-default profile relaunch paints its own
// skin + light/dark mode.
if (typeof window !== 'undefined') {
  const profile = readBootProfileKey()
  const pref = modePref.resolve(profile)
  const resolved = resolveMode(pref)
  const theme = deriveTheme(skinPref.resolve(profile), resolved)
  applyTheme(theme, resolved)
  syncNativeTheme(pref, renderedModeFor(theme.colors, resolved))
}

// ─── Context ────────────────────────────────────────────────────────────────

interface ThemeContextValue {
  theme: DesktopTheme
  themeName: string
  mode: ThemeMode
  /** The light/dark switch the user picked. */
  resolvedMode: 'light' | 'dark'
  /**
   * The mode actually painted, derived from the active background's luminance.
   * Differs from `resolvedMode` for skins that keep a bright surface in "dark"
   * (or vice-versa). Surface-bound UI (e.g. the terminal palette) should key off
   * this so it matches what's on screen instead of inverting.
   */
  renderedMode: 'light' | 'dark'
  availableThemes: Array<{ name: string; label: string; description: string }>
  setTheme: (name: string) => void
  setMode: (mode: ThemeMode) => void
}

const SKIN_LIST = BUILTIN_THEME_LIST.map(({ name, label, description }) => ({ name, label, description }))

const ThemeContext = createContext<ThemeContextValue>({
  theme: nousTheme,
  themeName: DEFAULT_SKIN_NAME,
  mode: 'light',
  resolvedMode: 'light',
  renderedMode: 'light',
  availableThemes: SKIN_LIST,
  setTheme: () => {},
  setMode: () => {}
})

export function ThemeProvider({ children }: { children: ReactNode }) {
  // Skin + mode are assigned per profile; the active profile drives which
  // appearance shows. Single-profile users only ever see "default", so their
  // behavior is unchanged.
  const profileKey = normalizeProfileKey(useStore($activeGatewayProfile))

  // Built-ins + user-installed + registry-contributed themes. Reactive so an
  // import or a plugin registration shows up live in the palette, settings
  // grid, and `/skin` without a reload.
  const userThemes = useStore($userThemes)
  const backendThemes = useStore($backendThemes)
  const registryVersion = useStore($registryVersion)

  const availableThemes = useMemo(
    () =>
      listAllThemes().map(({ name, label, description }) => ({
        name,
        label,
        description
      })),
    // userThemes + backendThemes + registryVersion ARE listAllThemes' reactivity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [userThemes, backendThemes, registryVersion]
  )

  const [themeName, setThemeNameState] = useState(() =>
    typeof window === 'undefined' ? DEFAULT_SKIN_NAME : skinPref.resolve(readBootProfileKey())
  )

  const [mode, setModeState] = useState<ThemeMode>(() =>
    typeof window === 'undefined' ? 'light' : modePref.resolve(readBootProfileKey())
  )

  // Follow profile switches: paint the profile's assigned skin + mode and
  // remember it for the next boot's first paint.
  useEffect(() => {
    rememberActiveProfileKey(profileKey)
    setThemeNameState(skinPref.resolve(profileKey))
    setModeState(modePref.resolve(profileKey))
  }, [profileKey])

  const systemDark = useMediaQuery('(prefers-color-scheme: dark)')
  const resolvedMode = resolveMode(mode, systemDark)

  const activeTheme = useMemo(
    () => deriveTheme(themeName, resolvedMode),
    // deriveTheme resolves its seed through the merged registry, so the theme
    // stores are its reactivity too — an in-place palette edit of the ACTIVE
    // skin (live theme authoring) must repaint, not just a name switch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [themeName, resolvedMode, userThemes, backendThemes, registryVersion]
  )

  // What actually gets painted (matches the `.dark` class applyTheme toggles).
  const renderedMode = useMemo(() => renderedModeFor(activeTheme.colors, resolvedMode), [activeTheme, resolvedMode])

  useEffect(() => applyTheme(activeTheme, resolvedMode), [activeTheme, resolvedMode])

  // Keep the native window appearance pinned to the app theme (vibrancy
  // material, titlebar, new-window pre-paint background).
  useEffect(() => syncNativeTheme(mode, renderedMode), [mode, renderedMode])

  // Assign to whichever profile is live right now (read fresh so the callbacks
  // stay stable across profile switches).
  const liveProfile = () => normalizeProfileKey($activeGatewayProfile.get())

  const setTheme = useCallback((name: string) => {
    const next = normalizeSkin(name)
    setThemeNameState(next)
    skinPref.assign(liveProfile(), next)
  }, [])

  const setMode = useCallback((next: ThemeMode) => {
    setModeState(next)
    modePref.assign(liveProfile(), next)
  }, [])

  // Drain a backend-driven skin switch (Hermes authoring/activating a skin from a
  // prompt, or `/skin` on another surface). setTheme persists it per profile, so
  // the choice sticks like any manual pick.
  const pendingSkin = useStore($pendingSkinApply)
  const pendingMode = useStore($pendingModeApply)

  useEffect(() => {
    if (pendingSkin) {
      setTheme(pendingSkin)
      $pendingSkinApply.set(null)
    }
  }, [pendingSkin, setTheme])

  useEffect(() => {
    if (pendingMode) {
      setMode(pendingMode)
      $pendingModeApply.set(null)
    }
  }, [pendingMode, setMode])

  // The light/dark toggle (Shift+X by default) is owned by the keybind runtime
  // (`appearance.toggleMode`) so it shows up in the hotkey map and is rebindable.

  const value = useMemo<ThemeContextValue>(
    () => ({ theme: activeTheme, themeName, mode, resolvedMode, renderedMode, availableThemes, setTheme, setMode }),
    [activeTheme, themeName, mode, resolvedMode, renderedMode, availableThemes, setTheme, setMode]
  )

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export const useTheme = (): ThemeContextValue => useContext(ThemeContext)
