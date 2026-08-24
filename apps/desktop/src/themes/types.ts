/**
 * Desktop app theme model.
 *
 *   colors      — Tailwind color tokens written directly to CSS vars.
 *   darkColors  — optional hand-tuned dark variant (else `colors` is reused
 *                 unchanged for dark, and a synth pass generates light).
 *   typography — font families + optional stylesheet URL.
 *   skinBinding — complete UGUI StyleModel parameters consumed as CSS variables.
 *
 * Catalyst-native themes live in `presets.ts`; canonical UGUI skins are bundled
 * automatically from `genui/ugui/skins/bindings/*.json`.
 */

export interface DesktopThemeColors {
  background: string
  foreground: string
  card: string
  cardForeground: string
  muted: string
  mutedForeground: string
  popover: string
  popoverForeground: string
  primary: string
  primaryForeground: string
  secondary: string
  secondaryForeground: string
  accent: string
  accentForeground: string
  border: string
  input: string
  /** Generic focus ring — buttons, inputs, etc. */
  ring: string
  /**
   * Brand-accent stroke — focus rings, streaming cursors, active session
   * pills, branded scrollbars, text selection. Falls back to `ring`.
   * Aliased to the DS `--midground` token.
   */
  midground?: string
  /** Auto-derived from `midground` luminance when omitted. */
  midgroundForeground?: string
  /** Composer outline / focus color. Falls back to `midground`. */
  composerRing?: string
  destructive: string
  destructiveForeground: string
  sidebarBackground?: string
  sidebarBorder?: string
  userBubble?: string
  userBubbleBorder?: string
}

export interface DesktopThemeTypography {
  fontSans: string
  fontMono: string
  /** Google/Bunny/self-hosted font stylesheet URL. */
  fontUrl?: string
}

export type ThemeMode = 'light' | 'dark' | 'system'

export type UgUiStyleSlot = Record<string, string>

/** Complete UGUI StyleModel binding carried without flattening or host-specific loss. */
export interface UgUiSkinBinding {
  palette: UgUiStyleSlot
  typography: UgUiStyleSlot
  geometry: UgUiStyleSlot
  'border-model': UgUiStyleSlot
  elevation: UgUiStyleSlot
  density: UgUiStyleSlot
  motion: UgUiStyleSlot
  chrome: UgUiStyleSlot
}

/**
 * Integrated-terminal ANSI palette (xterm `ITheme`, minus `background`).
 *
 * Populated only when a converted VS Code theme ships a full `terminal.ansi*`
 * set; otherwise the terminal keeps its built-in VS Code default palette.
 * `background` is intentionally absent — the pane always paints the live skin
 * surface so it stays translucent.
 */
export interface DesktopTerminalPalette {
  foreground?: string
  cursor?: string
  /** Keeps its source alpha — xterm blends it over the surface. */
  selectionBackground?: string
  black?: string
  red?: string
  green?: string
  yellow?: string
  blue?: string
  magenta?: string
  cyan?: string
  white?: string
  brightBlack?: string
  brightRed?: string
  brightGreen?: string
  brightYellow?: string
  brightBlue?: string
  brightMagenta?: string
  brightCyan?: string
  brightWhite?: string
}

export interface DesktopTheme {
  name: string
  label: string
  description: string
  /** Light palette (also reused for dark when `darkColors` is omitted). */
  colors: DesktopThemeColors
  /** Hand-tuned dark palette. Skins like `nous` ship one. */
  darkColors?: DesktopThemeColors
  typography?: Partial<DesktopThemeTypography>
  /** Light-variant terminal ANSI palette (also the fallback for dark). */
  terminal?: DesktopTerminalPalette
  /** Dark-variant terminal ANSI palette. Falls back to `terminal`. */
  darkTerminal?: DesktopTerminalPalette
  /** Canonical UGUI StyleModel parameters; Catalyst maps all slots to CSS variables. */
  skinBinding?: UgUiSkinBinding
  /** Fixed-polarity authored skins remain faithful when the global mode changes. */
  fixedMode?: 'light' | 'dark'
}
