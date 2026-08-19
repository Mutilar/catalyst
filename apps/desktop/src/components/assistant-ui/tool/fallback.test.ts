import { describe, expect, it } from 'vitest'

import { MODEL_VISIBLE_TOOL_RESULT_KEY } from '@/lib/tool-presentation'

import { mcpModelTrace, shouldBoundToolGroup, technicalTrace, UNBOUNDABLE_TOOLS } from './fallback'

describe('shouldBoundToolGroup', () => {
  it('bounds long runs of ordinary tool calls', () => {
    expect(shouldBoundToolGroup(3, false)).toBe(true)
  })

  it('leaves short runs unbounded', () => {
    expect(shouldBoundToolGroup(2, false)).toBe(false)
  })

  it('never bounds a run holding an unboundable tool', () => {
    expect(shouldBoundToolGroup(3, true)).toBe(false)
  })
})

describe('UNBOUNDABLE_TOOLS', () => {
  it('exempts clarify forms and generated images from the window', () => {
    expect(UNBOUNDABLE_TOOLS.has('clarify')).toBe(true)
    expect(UNBOUNDABLE_TOOLS.has('image_generate')).toBe(true)
  })
})

describe('technicalTrace', () => {
  it('indents object payloads and persisted JSON strings', () => {
    expect(technicalTrace({ offset: 2, path: '/tmp/demo.txt' }, '{"success":true,"lines":["a","b"]}')).toBe(
      'Arguments:\n{\n  "offset": 2,\n  "path": "/tmp/demo.txt"\n}\n\nResult:\n{\n  "success": true,\n  "lines": [\n    "a",\n    "b"\n  ]\n}'
    )
  })

  it('leaves scalar strings untouched', () => {
    expect(technicalTrace(undefined, 'plain text')).toBe('Result:\nplain text')
    expect(technicalTrace(undefined, '"already quoted"')).toBe('Result:\n"already quoted"')
  })
})

describe('mcpModelTrace', () => {
  it('shows exact model-visible input and output without Hermes timing metadata', () => {
    expect(
      mcpModelTrace(
        {},
        {
          duration_s: 1.789,
          error: '🔴 LUCID · morph · malformed-args',
          [MODEL_VISIBLE_TOOL_RESULT_KEY]: { error: '🔴 LUCID · morph · malformed-args' }
        }
      )
    ).toBe('Input:\n{}\n\nOutput:\n{\n  "error": "🔴 LUCID · morph · malformed-args"\n}')
  })
})
