import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { McpUguiDocument as Document } from '@/lib/tool-presentation'

import { McpUguiDocument, projectUguiAction } from './mcp-ugui'

const mocks = vi.hoisted(() => ({ invokeUguiAction: vi.fn() }))

vi.mock('@/hermes', () => ({ invokeUguiAction: mocks.invokeUguiAction }))

afterEach(() => {
  cleanup()
  mocks.invokeUguiAction.mockReset()
})

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

  it('invokes an exact authored LUCID action and replaces the card with returned UGUI', async () => {
    const actionable = {
      ...document,
      provenance: {
        parentHash: `sha256:${'a'.repeat(64)}`
      },
      receipt: {
        action_provenance: [
          {
            id: 'lucid.response.execution',
            state: 'AVAILABLE',
            provenance_hash: `sha256:${'a'.repeat(64)}`
          }
        ]
      },
      actions: [
        {
          id: 'lucid.response.execution',
          label: 'Inspect execution',
          action: 'lucid.show.execution',
          value: `dispatch:${'b'.repeat(64)}`,
          intent: {
            verb: 'show',
            arguments: { view: 'execution', id: `dispatch:${'b'.repeat(64)}` }
          }
        }
      ]
    } satisfies Document
    mocks.invokeUguiAction.mockResolvedValue({
      ok: true,
      result: {
        structuredContent: {
          ...document,
          header: [{ id: 'title', type: 'text', body: 'Current execution' }],
          actions: []
        }
      }
    })

    render(<McpUguiDocument document={actionable} />)
    const button = screen.getByRole('button', { name: 'Inspect execution' })
    fireEvent.click(button)
    fireEvent.click(button)

    await waitFor(() => expect(mocks.invokeUguiAction).toHaveBeenCalledWith(actionable, 'lucid.response.execution', false))
    expect(mocks.invokeUguiAction).toHaveBeenCalledTimes(1)
    expect(await screen.findByRole('heading', { name: 'Current execution' })).toBeTruthy()
  })

  it('requires an explicit second click before exact cancellation', async () => {
    const cancellable = {
      ...document,
      provenance: {
        parentHash: `sha256:${'a'.repeat(64)}`
      },
      receipt: {
        action_provenance: [
          {
            id: 'lucid.response.cancel',
            state: 'AVAILABLE',
            provenance_hash: `sha256:${'a'.repeat(64)}`
          }
        ]
      },
      actions: [
        {
          id: 'lucid.response.cancel',
          label: 'Cancel',
          action: 'lucid.cancel.dispatch',
          value: `dispatch:${'b'.repeat(64)}`,
          intent: {
            verb: 'cancel',
            arguments: { task: 'fleet.dispatch', dispatch_id: `dispatch:${'b'.repeat(64)}` }
          },
          requiresConfirmation: 'exact'
        }
      ]
    } satisfies Document
    mocks.invokeUguiAction.mockResolvedValue({ ok: true, result: {} })

    render(<McpUguiDocument document={cancellable} />)
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(mocks.invokeUguiAction).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Confirm Cancel' }))

    await waitFor(() => expect(mocks.invokeUguiAction).toHaveBeenCalledWith(cancellable, 'lucid.response.cancel', true))
  })

  it('renders incomplete compose actions as disabled rather than inert affordances', () => {
    render(
      <McpUguiDocument
        document={{
          ...document,
          actions: [{ id: 'lucid.response.steer', label: 'Steer', action: 'lucid.steer.compose' }]
        }}
      />
    )

    expect((screen.getByRole('button', { name: 'Steer' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('admits future complete read actions without a renderer handler allowlist', () => {
    const action = {
      id: 'lucid.response.inspect',
      label: 'Inspect fleet',
      action: 'lucid.get.inspect',
      value: 'fleet',
      intent: { verb: 'get', arguments: { path: 'fleet' } }
    }
    const value = {
      ...document,
      provenance: { parentHash: `sha256:${'a'.repeat(64)}` },
      receipt: {
        action_provenance: [
          {
            id: action.id,
            state: 'AVAILABLE',
            provenance_hash: `sha256:${'a'.repeat(64)}`
          }
        ]
      },
      actions: [action]
    } satisfies Document

    expect(projectUguiAction(value, action, 0).executable).toBe(true)
  })

  it('disables stale and unconfirmed mutating actions with actionable reasons', () => {
    const action = {
      id: 'lucid.response.restore',
      label: 'Restore',
      action: 'lucid.set.restore',
      intent: { verb: 'set', arguments: { path: 'setting', value: 'prior' } }
    }
    const value = {
      ...document,
      provenance: { parentHash: `sha256:${'a'.repeat(64)}` },
      receipt: {
        action_provenance: [
          {
            id: action.id,
            state: 'AVAILABLE',
            provenance_hash: `sha256:${'a'.repeat(64)}`
          }
        ]
      },
      actions: [action]
    } satisfies Document

    const missingConfirmation = projectUguiAction(value, action, 0)
    expect(missingConfirmation.executable).toBe(false)
    expect(missingConfirmation.reason).toContain('exact confirmation')

    const stale = projectUguiAction(
      {
        ...value,
        receipt: {
          action_provenance: [
            {
              id: action.id,
              state: 'AVAILABLE',
              provenance_hash: `sha256:${'c'.repeat(64)}`
            }
          ]
        }
      },
      { ...action, requiresConfirmation: 'exact' },
      0
    )
    expect(stale.executable).toBe(false)
    expect(stale.reason).toContain('unavailable')
  })
})
