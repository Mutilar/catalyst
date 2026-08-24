import { act, cleanup, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { __resetBackendSkinSync, ingestBackendSkin, ingestLucidHostAppearance } from './backend-sync'
import { ThemeProvider } from './context'

// The live-authoring loop: Hermes writes/edits one skin file and every surface
// repaints. An in-place edit keeps the NAME — only the palette moves.
const bloomberg = (foreground: string) => ({
  name: 'bloomberg',
  colors: { background: '#000000', ui_text: foreground, ui_accent: '#ff8000' }
})

const cssVar = (name: string) => window.document.documentElement.style.getPropertyValue(name)

describe('ThemeProvider ← backend skin sync', () => {
  beforeEach(() => {
    window.localStorage.clear()
    __resetBackendSkinSync()
  })

  afterEach(cleanup)

  it('applies an activated backend skin', () => {
    render(
      <ThemeProvider>
        <div />
      </ThemeProvider>
    )

    act(() => ingestBackendSkin(bloomberg('#ff9f0a'), { apply: true }))

    expect(cssVar('--theme-foreground')).toBe('#ff9f0a')
    expect(cssVar('--theme-background-seed')).toBe('#000000')
  })

  it('repaints an in-place edit of the ACTIVE skin (same name, new palette)', () => {
    render(
      <ThemeProvider>
        <div />
      </ThemeProvider>
    )

    act(() => ingestBackendSkin(bloomberg('#ff9f0a'), { apply: true }))
    expect(cssVar('--theme-foreground')).toBe('#ff9f0a')

    // Recolor the same skin file. The same-name apply guard correctly no-ops
    // (protects manual desktop picks), so the repaint must come from the
    // registry update reaching the active theme derivation.
    act(() => ingestBackendSkin(bloomberg('#ff2d95'), { apply: true }))
    expect(cssVar('--theme-foreground')).toBe('#ff2d95')
  })

  it('does not repaint an edit to an INACTIVE skin', () => {
    render(
      <ThemeProvider>
        <div />
      </ThemeProvider>
    )

    act(() => ingestBackendSkin(bloomberg('#ff9f0a'), { apply: true }))

    // A different skin registered without apply (e.g. seeded on reconnect)
    // must not touch the painted theme.
    act(() =>
      ingestBackendSkin({ name: 'forest', colors: { background: '#001100', ui_text: '#66ff66' } }, { apply: false })
    )
    expect(cssVar('--theme-foreground')).toBe('#ff9f0a')
  })

  it('applies LUCID light mode and the complete Windows 95 UGUI binding', () => {
    render(
      <ThemeProvider>
        <div />
      </ThemeProvider>
    )

    act(() => {
      ingestLucidHostAppearance({
        schema: 'lucid-host-appearance/1',
        apply: true,
        mode: 'light',
        skin: 'windows-95'
      })
    })

    const root = window.document.documentElement
    expect(root.dataset.hermesTheme).toBe('windows-95')
    expect(root.dataset.hermesMode).toBe('light')
    expect(root.dataset.hermesBorderModel).toBe('bevel')
    expect(cssVar('--theme-background-seed')).toBe('#c0c0c0')
    expect(cssVar('--skin-palette-desktop')).toBe('#008081')
    expect(cssVar('--skin-geometry-radius-scale')).toBe('0px')
    expect(cssVar('--skin-density-control-height')).toBe('23px')
    expect(cssVar('--skin-chrome-title-bar')).toContain('background:#000181')
    expect(cssVar('--skin-motion-none')).toBe('0ms')
  })
})
