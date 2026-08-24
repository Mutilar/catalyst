import { describe, expect, it } from 'vitest'

import { UGUI_THEMES } from './ugui-skins'

const STYLE_SLOTS = [
  'palette',
  'typography',
  'geometry',
  'border-model',
  'elevation',
  'density',
  'motion',
  'chrome'
] as const

describe('UGUI skin catalog', () => {
  it('bundles every generated binding and preserves the complete Windows 95 style model', () => {
    const windows95 = UGUI_THEMES['windows-95']

    expect(windows95).toBeDefined()
    expect(windows95.label).toBe('Windows 95')
    expect(windows95.fixedMode).toBe('light')
    expect(Object.keys(windows95.skinBinding ?? {}).sort()).toEqual([...STYLE_SLOTS].sort())
    expect(windows95.skinBinding?.palette.surface).toBe('#c0c0c0')
    expect(windows95.skinBinding?.palette.desktop).toBe('#008081')
    expect(windows95.skinBinding?.geometry['radius-scale']).toBe('0px')
    expect(windows95.skinBinding?.['border-model'].bevel).toBe('outset 2px')
    expect(windows95.skinBinding?.chrome['title-bar']).toContain('background:#000181')
    expect(windows95.skinBinding?.motion.none).toBe('0ms')
  })
})
