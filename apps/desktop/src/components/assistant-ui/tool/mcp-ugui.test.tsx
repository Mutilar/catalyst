import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import type { McpUguiDocument as Document } from '@/lib/tool-presentation'

import { McpUguiDocument } from './mcp-ugui'

afterEach(cleanup)

const document: Document = {
  schema: 'lucid-ugui-response/1',
  id: 'lucid.response',
  type: 'lucid',
  verb: 'morph',
  state: 'complete',
  header: [{ id: 'title', type: 'text', body: 'LUCID morph' }],
  sections: [
    { id: 'status', type: 'status', signal: '🟢', body: 'Complete' },
    {
      id: 'result',
      type: 'key_value',
      heading: 'Result',
      rows: [{ id: 'artifact', key: 'Artifact', value: 'one-pager' }]
    }
  ],
  actions: [{ id: 'inspect', label: 'Inspect' }]
}

describe('McpUguiDocument', () => {
  it('renders canonical UGUI semantics as visual tool-card content', () => {
    const { container } = render(<McpUguiDocument document={document} />)

    expect(screen.getByRole('heading', { name: 'LUCID morph' })).toBeTruthy()
    expect(screen.getByText('Complete')).toBeTruthy()
    expect(screen.getByText('Artifact')).toBeTruthy()
    expect(screen.getByText('one-pager')).toBeTruthy()
    expect(screen.getByText('Inspect')).toBeTruthy()
    expect(container.querySelector('[data-mcp-ugui="lucid-ugui-response/1"]')).toBeTruthy()
  })

  it('renders repository search match tables instead of hiding structured rows', () => {
    render(
      <McpUguiDocument
        document={{
          ...document,
          verb: 'get',
          header: [{ id: 'title', type: 'text', body: 'LUCID get search' }],
          sections: [
            {
              id: 'matches',
              type: 'data_table',
              heading: 'Matches',
              columns: ['Path', 'Line / count', 'Match', 'Context'],
              rows: [
                [
                  'run/src/tui.rs',
                  '1071',
                  'fn dashboard_log_sources()',
                  '> 1071: fn dashboard_log_sources()'
                ]
              ]
            },
            {
              id: 'canonical-data',
              type: 'code',
              label: 'Canonical result data',
              value:
                '{"matches":[{"line":1071,"path":"run/src/tui.rs","text":"fn dashboard_log_sources()"}],"truncated":false}'
            }
          ]
        }}
      />
    )

    expect(screen.getByText('Matches')).toBeTruthy()
    expect(screen.getByText('run/src/tui.rs')).toBeTruthy()
    expect(screen.getByText('fn dashboard_log_sources()')).toBeTruthy()
    expect(screen.getByText('> 1071: fn dashboard_log_sources()')).toBeTruthy()
    expect(screen.getByText('Canonical result data')).toBeTruthy()
    expect(
      screen.getByText(
        '{"matches":[{"line":1071,"path":"run/src/tui.rs","text":"fn dashboard_log_sources()"}],"truncated":false}'
      )
    ).toBeTruthy()
  })
})
