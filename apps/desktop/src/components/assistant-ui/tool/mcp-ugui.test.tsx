import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { SIGNAL_GREEN } from '@/lib/ae-glyphs'
import type { McpUguiDocument as Document } from '@/lib/tool-presentation'
import { $pendingModeApply, $pendingSkinApply, __resetBackendSkinSync } from '@/themes/backend-sync'

import { canonicalGestaltStream } from '../../../lib/lucid-gestalt'

import { McpUguiDocument, projectUguiAction, residentUguiActionId } from './mcp-ugui'

const mocks = vi.hoisted(() => ({
  invokeUguiAction: vi.fn(),
  resolveUguiMediaReference: vi.fn()
}))

vi.mock('@/hermes', () => ({ invokeUguiAction: mocks.invokeUguiAction }))
vi.mock('@/lib/media', () => ({ resolveUguiMediaReference: mocks.resolveUguiMediaReference }))

afterEach(() => {
  cleanup()
  mocks.invokeUguiAction.mockReset()
  mocks.resolveUguiMediaReference.mockReset()
  __resetBackendSkinSync()
})

const document: Document = {
  schema: 'lucid-ugui-response/1',
  id: 'lucid.response',
  type: 'lucid',
  verb: 'morph',
  state: 'complete',
  header: [{ id: 'title', type: 'text', body: 'LUCID morph' }],
  sections: [
    { id: 'status', type: 'status', signal: SIGNAL_GREEN, body: 'Complete' },
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
  it('admits exact noun discovery and refuses disguised execution', () => {
    const provenance = `sha256:${'a'.repeat(64)}`

    const action = {
      id: 'discover-role', label: 'Choose role syntax', action: 'lucid.help.noun', value: 'role',
      intent: { verb: 'set', arguments: { help: 'role' } }
    }

    const value = {
      ...document, provenance: { parentHash: provenance }, actions: [action],
      receipt: { action_provenance: [{ id: action.id, state: 'AVAILABLE', provenance_hash: provenance }] }
    } satisfies Document

    expect(projectUguiAction(value, action, 0).executable).toBe(true)
    expect(projectUguiAction(value, action, 0).requiresConfirmation).toBe(false)

    for (const args of [{ path: 'role' }, { help: 'role', value: 'EM' }, { help: 'other' }]) {
      expect(projectUguiAction(value, { ...action, intent: { verb: 'set', arguments: args } }, 0).executable).toBe(false)
    }
  })

  it('admits provenance-bound SET help without granting a mutation', () => {
    const provenance = `sha256:${'a'.repeat(64)}`

    const action = {
      id: 'onboarding-signin', label: 'Sign in', action: 'lucid.help.verb', value: 'set',
      intent: { verb: 'set', arguments: {} }
    }

    const value = {
      ...document, provenance: { parentHash: provenance }, actions: [action],
      receipt: { action_provenance: [{ id: action.id, state: 'AVAILABLE', provenance_hash: provenance }] }
    } satisfies Document

    expect(projectUguiAction(value, action, 0).executable).toBe(true)
    expect(projectUguiAction(value, action, 0).requiresConfirmation).toBe(false)
    expect(projectUguiAction(value, {
      ...action, intent: { verb: 'set', arguments: { path: 'role', value: '<identity>' } }
    }, 0).executable).toBe(false)
    expect(projectUguiAction(value, {
      ...action, action: 'lucid.set.continue', value: provenance,
      intent: { verb: 'set', arguments: { path: 'role', value: 'EM' } }
    }, 0).executable).toBe(false)
  })

  it('consumes a typed LUCID appearance host effect', async () => {
    render(
      <McpUguiDocument
        document={{
          ...document,
          hostEffect: {
            schema: 'lucid-host-appearance/1',
            apply: true,
            mode: 'light',
            skin: 'windows-95'
          }
        }}
      />
    )

    await waitFor(() => expect($pendingModeApply.get()).toBe('light'))
    expect($pendingSkinApply.get()).toBe('windows-95')
  })

  it('routes resident app events by the UGUI-authored action identity', () => {
    const button = window.document.createElement('button')
    const label = window.document.createElement('span')
    button.setAttribute('data-ugui-action', 'snake-start')
    button.append(label)

    expect(residentUguiActionId(label)).toBe('snake-start')
    const obsolete = window.document.createElement('button')
    obsolete.setAttribute('data-ugui-id', 'legacy-action')
    expect(residentUguiActionId(obsolete)).toBe('')
    expect(residentUguiActionId(window.document.createTextNode('outside'))).toBe('')
  })

  it('renders canonical UGUI semantics as visual tool-card content', () => {
    const { container } = render(<McpUguiDocument document={document} />)

    expect(screen.getByRole('heading', { name: 'LUCID morph' })).toBeTruthy()
    expect(screen.getByText('Complete')).toBeTruthy()
    expect(screen.getByText('Artifact')).toBeTruthy()
    expect(screen.getByText('one-pager')).toBeTruthy()
    expect(screen.getByText('Inspect')).toBeTruthy()
    expect(container.querySelector('[data-mcp-ugui="lucid-ugui-response/1"]')).toBeTruthy()
  })

  it('resolves a projected screen reference into a true accessible image', async () => {
    mocks.resolveUguiMediaReference.mockResolvedValue('data:image/png;base64,iVBORw0KGgo=')

    const mediaDocument = {
      ...document,
      sections: [
        {
          id: 'device-screenshot',
          type: 'image',
          src: 'artifact://screen/screen-123-00-abcdef.preview.png',
          alt: 'Enrolled device screenshot',
          fit: 'contain',
          sha256: `sha256:${'a'.repeat(64)}`,
          pixelWidth: 1080,
          pixelHeight: 1920,
          provenance: {
            owner: 'butler::screen',
            retention: 'private-frozen',
            network_used: false
          }
        }
      ]
    } satisfies Document

    const { container } = render(<McpUguiDocument document={mediaDocument} />)
    const image = await screen.findByRole('img', { name: 'Enrolled device screenshot' })

    expect(mocks.resolveUguiMediaReference).toHaveBeenCalledWith('artifact://screen/screen-123-00-abcdef.preview.png')
    expect(image.getAttribute('src')).toBe('data:image/png;base64,iVBORw0KGgo=')
    expect(container.querySelector('[data-ugui-primitive="image"]')).toBeTruthy()
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
          value: ['| Rule | Meaning |', '|---|---|', '| **D.R.Y.** | Keep `one source` authoritative. |'].join('\n')
        }
      ]
    } satisfies Document

    const { container } = render(<McpUguiDocument document={markdownDocument} />)

    expect(container.querySelector('[data-ugui-renderer="streamdown"]')).toBeTruthy()
    expect(screen.getByText('D.R.Y.').closest('strong')).toBeTruthy()
    expect(screen.getByText('one source').closest('code')).toBeTruthy()
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

  it('uses the engine width contract in a container-responsive grid', () => {
    const responsiveDocument = {
      ...document,
      sections: [
        { id: 'left', type: 'status', signal: SIGNAL_GREEN, body: 'Left', width: 5 },
        { id: 'right', type: 'status', signal: SIGNAL_GREEN, body: 'Right', width: 7 }
      ]
    } satisfies Document

    const { container } = render(<McpUguiDocument document={responsiveDocument} />)
    const grid = container.querySelector('[data-ugui-layout="responsive-grid"]')
    const left = grid?.querySelector('[data-ugui-width="5"]')
    const right = grid?.querySelector('[data-ugui-width="7"]')

    expect(grid).toBeTruthy()
    expect(left?.className).toContain('col-span-12')
    expect(left?.className).toContain('@lg:col-span-5')
    expect(right?.className).toContain('@lg:col-span-7')
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

    await waitFor(() => expect(mocks.invokeUguiAction).toHaveBeenCalledWith(value, help.id, false, {}))
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

    await waitFor(() =>
      expect(mocks.invokeUguiAction).toHaveBeenCalledWith(actionable, 'lucid.response.execution', false, {})
    )
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

    mocks.invokeUguiAction.mockResolvedValue({
      ok: true,
      result: {
        structuredContent: {
          ...document,
          header: [{ id: 'title', type: 'text', body: 'Cancellation complete' }],
          actions: []
        }
      }
    })

    render(<McpUguiDocument document={cancellable} />)
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() =>
      expect(mocks.invokeUguiAction).toHaveBeenCalledWith(cancellable, 'lucid.response.cancel', false, {})
    )
    expect(mocks.invokeUguiAction).toHaveBeenCalledTimes(1)
    expect(await screen.findByRole('heading', { name: 'Cancellation complete' })).toBeTruthy()
  })

  it('refuses false completion when an action returns no replacement UGUI', async () => {
    const provenance = `sha256:${'a'.repeat(64)}`

    const action = {
      id: 'lucid.response.inspect',
      label: 'Refresh',
      action: 'lucid.get.readback',
      value: 'gates',
      intent: { verb: 'get', arguments: { path: 'gates' } }
    }

    const actionable = {
      ...document,
      provenance: { parentHash: provenance },
      receipt: {
        action_provenance: [{ id: action.id, state: 'AVAILABLE', provenance_hash: provenance }]
      },
      actions: [action]
    } satisfies Document

    mocks.invokeUguiAction.mockResolvedValue({ ok: true, result: {} })

    render(<McpUguiDocument document={actionable} />)
    fireEvent.click(screen.getByRole('button', { name: 'Refresh' }))

    expect(await screen.findByText('LUCID action completed without a replacement UGUI document')).toBeTruthy()
    expect(screen.queryByText('Refresh completed.')).toBeNull()
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

    mocks.invokeUguiAction.mockResolvedValue({
      ok: true,
      result: {
        structuredContent: {
          ...document,
          header: [{ id: 'title', type: 'text', body: 'Steering accepted' }],
          actions: []
        }
      }
    })

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
    expect(await screen.findByRole('heading', { name: 'Steering accepted' })).toBeTruthy()
  })

  it('adopts subsequent action documents as a multi-step CYOA branch', async () => {
    const provenance = `sha256:${'a'.repeat(64)}`
    const nextProvenance = `sha256:${'c'.repeat(64)}`

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
        action_provenance: [{ id: choice.id, state: 'AVAILABLE', provenance_hash: provenance }]
      },
      actions: [choice]
    } satisfies Document

    const inspect = {
      id: 'lucid.gestalt.action.0',
      label: 'Inspect quality',
      action: 'lucid.get.continue',
      value: nextProvenance,
      intent: { verb: 'get', arguments: { path: 'gates' } }
    }

    const choices = {
      ...document,
      header: [{ id: 'title', type: 'text', body: 'One-pager choices' }],
      provenance: { parentHash: nextProvenance },
      receipt: {
        action_provenance: [{ id: inspect.id, state: 'AVAILABLE', provenance_hash: nextProvenance }]
      },
      actions: [inspect]
    } satisfies Document

    const quality = {
      ...document,
      header: [{ id: 'title', type: 'text', body: 'Quality gates' }],
      actions: []
    } satisfies Document

    mocks.invokeUguiAction
      .mockResolvedValueOnce({
        ok: true,
        result: {
          schema: 'hermes-tool-result-channels/1',
          model: canonicalGestaltStream({
            signal: SIGNAL_GREEN,
            verb: 'morph',
            noun: 'one-pager',
            argument: 'ready'
          }),
          presentation: {
            structuredContent: choices
          }
        }
      })
      .mockResolvedValueOnce({ ok: true, result: { structuredContent: quality } })

    const { rerender } = render(<McpUguiDocument document={choose} />)
    fireEvent.click(screen.getByRole('button', { name: 'One-pager' }))

    await waitFor(() => expect(mocks.invokeUguiAction).toHaveBeenCalledWith(choose, choice.id, false, {}))
    expect(mocks.invokeUguiAction).toHaveBeenCalledTimes(1)
    expect(screen.queryByText(/Confirmation required/)).toBeNull()
    expect(await screen.findByRole('heading', { name: 'One-pager choices' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Inspect quality' }))
    await waitFor(() => expect(mocks.invokeUguiAction).toHaveBeenCalledWith(choices, inspect.id, false, {}))
    expect(mocks.invokeUguiAction).toHaveBeenCalledTimes(2)
    expect(await screen.findByRole('heading', { name: 'Quality gates' })).toBeTruthy()
    rerender(<McpUguiDocument document={{ ...choose }} />)
    expect(screen.getByRole('heading', { name: 'Quality gates' })).toBeTruthy()
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
