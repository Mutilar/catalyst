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

  it('renders Markdown code primitives through Streamdown with source-copy chrome', () => {
    const markdownDocument = {
      ...document,
      sections: [
        {
          id: 'markdown-context',
          type: 'code',
          label: 'Context',
          language: 'markdown',
          value: [
            '| Rule | Meaning |',
            '|---|---|',
            '| **D.R.Y.** | Keep `one source` authoritative. |'
          ].join('\n')
        }
      ]
    } satisfies Document

    const { container } = render(<McpUguiDocument document={markdownDocument} />)

    expect(container.querySelector('[data-ugui-renderer="streamdown"]')).toBeTruthy()
    expect(screen.getByText('D.R.Y.').tagName).toBe('STRONG')
    expect(screen.getByText('one source').tagName).toBe('CODE')
    expect(screen.getByRole('table')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Copy Markdown source' })).toBeTruthy()
  })

  it('retains Shiki for non-Markdown code primitives', () => {
    const sourceDocument = {
      ...document,
      sections: [
        {
          id: 'typescript-context',
          type: 'code',
          label: 'Context',
          language: 'typescript',
          value: 'const value = 1'
        }
      ]
    } satisfies Document

    const { container } = render(<McpUguiDocument document={sourceDocument} />)

    expect(container.querySelector('[data-ugui-renderer="shiki"]')).toBeTruthy()
    expect(container.querySelector('[data-ugui-renderer="streamdown"]')).toBeNull()
  })

  it('renders universal current-verb Help in the header and invokes it once', async () => {
    const provenance = `sha256:${'a'.repeat(64)}`
    const help = {
      id: 'lucid.response.help',
      label: 'Help',
      action: 'lucid.help.verb',
      value: 'get',
      intent: { verb: 'get', arguments: {} }
    }
    const value = {
      ...document,
      verb: 'get',
      provenance: { parentHash: provenance },
      receipt: {
        action_provenance: [{ id: help.id, state: 'AVAILABLE', provenance_hash: provenance }]
      },
      actions: [help]
    } satisfies Document
    mocks.invokeUguiAction.mockResolvedValue({ ok: true, result: {} })

    render(<McpUguiDocument document={value} />)
    fireEvent.click(screen.getByRole('button', { name: 'Help' }))

    await waitFor(() => expect(mocks.invokeUguiAction).toHaveBeenCalledWith(value, help.id, false))
    expect(mocks.invokeUguiAction).toHaveBeenCalledTimes(1)
    expect(screen.queryByText('Help')).toBeNull()
  })

  it('renders repository search semantics without raw canonical payloads', async () => {
    const { container } = render(
      <McpUguiDocument
        document={{
          ...document,
          verb: 'get',
          header: [{ id: 'title', type: 'text', body: 'LUCID get search' }],
          sections: [
            {
              id: 'match-0',
              type: 'nested',
              title: 'run/src/tui.rs:1071',
              expanded: true,
              sections: [
                {
                  id: 'match-0-source',
                  type: 'code',
                  label: 'Match',
                  language: 'rust',
                  value: 'fn dashboard_log_sources()'
                },
                {
                  id: 'match-0-context',
                  type: 'code',
                  label: 'Context',
                  language: 'rust',
                  value: 'fn dashboard_log_sources() {\n    // context\n}'
                }
              ]
            }
          ]
        }}
      />
    )

    expect(screen.getByText('run/src/tui.rs:1071')).toBeTruthy()
    const code = container.querySelectorAll('[data-ugui-primitive="code"]')
    expect(code).toHaveLength(2)
    await waitFor(() => {
      expect(code[0].textContent).toContain('Match')
      expect(code[0].textContent).toContain('rust')
      expect(code[0].textContent).toContain('fn dashboard_log_sources()')
      expect(code[1].textContent).toContain('Context')
      expect(code[1].textContent).toContain('fn dashboard_log_sources() {')
    })
    expect(screen.queryByText('Canonical result data')).toBeNull()
    expect(screen.queryByText(/\{"matches":/)).toBeNull()
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

  it('cancels in one click without confirmation', async () => {
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
            arguments: { id: `dispatch:${'b'.repeat(64)}`, mode: 'graceful' }
          }
        }
      ]
    } satisfies Document
    mocks.invokeUguiAction.mockResolvedValue({ ok: true, result: {} })

    render(<McpUguiDocument document={cancellable} />)
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() =>
      expect(mocks.invokeUguiAction).toHaveBeenCalledWith(cancellable, 'lucid.response.cancel', false)
    )
    expect(mocks.invokeUguiAction).toHaveBeenCalledTimes(1)
  })

  it('submits one bounded STEER input after exact confirmation', async () => {
    const dispatchId = `dispatch:${'b'.repeat(64)}`
    const steerable = {
      ...document,
      provenance: { parentHash: `sha256:${'a'.repeat(64)}` },
      receipt: {
        action_provenance: [
          {
            id: 'lucid.response.steer',
            state: 'AVAILABLE',
            provenance_hash: `sha256:${'a'.repeat(64)}`
          }
        ]
      },
      actions: [
        {
          id: 'lucid.response.steer',
          label: 'Steer',
          action: 'lucid.steer.compose',
          value: dispatchId,
          requiresConfirmation: 'exact',
          inputs: [
            {
              id: 'intent_delta',
              type: 'text',
              label: 'Correction',
              required: true,
              maxLength: 4000
            }
          ],
          intent: {
            verb: 'steer',
            arguments: { dispatch_id: dispatchId, intent_delta: '' }
          }
        }
      ]
    } satisfies Document
    mocks.invokeUguiAction.mockResolvedValue({ ok: true, result: {} })

    render(<McpUguiDocument document={steerable} />)
    fireEvent.change(screen.getByRole('textbox', { name: 'Correction' }), {
      target: { value: 'Inspect the exact response validator.' }
    })
    fireEvent.click(screen.getByRole('button', { name: 'Steer' }))
    expect(mocks.invokeUguiAction).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Confirm Steer' }))

    await waitFor(() =>
      expect(mocks.invokeUguiAction).toHaveBeenCalledWith(steerable, 'lucid.response.steer', true, {
        intent_delta: 'Inspect the exact response validator.'
      })
    )
    expect(mocks.invokeUguiAction).toHaveBeenCalledTimes(1)
  })

  it('executes one read-like MORPH choice in one call and adopts its returned UGUI', async () => {
    const provenance = `sha256:${'a'.repeat(64)}`
    const choice = {
      id: 'lucid.response.morph.choice.0',
      label: 'One-pager',
      action: 'lucid.morph.choice',
      value: 'one-pager',
      intent: {
        verb: 'morph',
        arguments: { codebook: 'one-pager', operation: 'shard' }
      }
    }
    const choose = {
      ...document,
      provenance: { parentHash: provenance },
      receipt: {
        action_provenance: [
          { id: choice.id, state: 'AVAILABLE', provenance_hash: provenance }
        ]
      },
      actions: [choice]
    } satisfies Document
    mocks.invokeUguiAction.mockResolvedValue({
      ok: true,
      result: {
        structuredContent: {
          ...document,
          header: [{ id: 'title', type: 'text', body: 'One-pager choices' }],
          actions: []
        }
      }
    })

    render(<McpUguiDocument document={choose} />)
    fireEvent.click(screen.getByRole('button', { name: 'One-pager' }))

    await waitFor(() => expect(mocks.invokeUguiAction).toHaveBeenCalledWith(choose, choice.id, false))
    expect(mocks.invokeUguiAction).toHaveBeenCalledTimes(1)
    expect(screen.queryByText(/Confirmation required/)).toBeNull()
    expect(await screen.findByRole('heading', { name: 'One-pager choices' })).toBeTruthy()
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
