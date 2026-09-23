import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import { DELIMITER_SEGMENT, IDENTITY_PENGUIN, RELATION_ACTION, SIGNAL_GREEN, SIGNAL_RED } from '@/lib/ae-glyphs'
import { canonicalGestaltStream } from '@/lib/lucid-gestalt'

import { DirectOperation } from './direct-operation'

const mocks = vi.hoisted(() => ({ submit: vi.fn() }))
vi.mock('@/app/chat/composer/focus', () => ({ requestComposerSubmit: mocks.submit }))

vi.mock('@/components/assistant-ui/ugui-text', () => ({
  UguiTextContent: ({
    text,
    copyText,
    allowContinuations,
    onContinuation
  }: {
    text: string
    copyText: string
    allowContinuations: boolean
    onContinuation?: (text: string) => void
  }) => (
    <div
      data-continuations={String(allowContinuations)}
      data-copy-payload={copyText}
      data-preparation-projection="true"
    >
      {text}
      {allowContinuations &&
        onContinuation &&
        ['Retry', 'Bypass', 'Help'].map(label => (
          <button key={label} onClick={() => onContinuation(label)}>
            {label}
          </button>
        ))}
    </div>
  )
}))

vi.mock('@/components/assistant-ui/tool/mcp-ugui', () => ({
  McpUguiDocument: ({
    document,
    onContinuation
  }: {
    document: { id: string; actions?: Array<{ value: string; label?: string }> }
    onContinuation?: (text: string) => void
  }) => {
    if (document.id === 'broken') {
      throw new Error('projection failed')
    }

    return (
      <div data-operation-projection="true">
        Rendered operation
        {document.actions?.map(action => (
          <button key={action.value} onClick={() => onContinuation?.(action.value)}>
            {action.label ?? 'Confirm proposal'}
          </button>
        ))}
      </div>
    )
  }
}))

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  mocks.submit.mockReset()
})

it.each(['COMPLETED', 'REFUSED'])('uses one structured operation view for a %s CLI receipt', state => {
  const source = JSON.stringify({
    document: {
      schema: 'lucid-ugui-response/1',
      type: 'document',
      id: 'direct-fixture',
      header: [{ type: 'text', body: state }],
      sections: [
        { type: 'code', heading: 'INPUT', language: 'text', value: 'git status' },
        { type: 'code', heading: 'OUTPUT', language: 'text', value: 'On branch main\nworking tree clean\n' }
      ],
      actions: []
    },
    diagnostic: { schema: 'catalyst-direct-operation/1', receipt: { ran: state === 'COMPLETED' } }
  })

  const { container } = render(<DirectOperation source={source} />)
  expect(container.querySelectorAll('[data-operation-projection]')).toHaveLength(1)
  expect(container.querySelector('[data-preparation-projection]')).toBeNull()
  expect(screen.getAllByRole('button', { name: 'Copy operation diagnostics' })).toHaveLength(1)
  expect(mocks.submit).not.toHaveBeenCalled()
})

it.each(['retry', 'bypass', 'help'] as const)(
  'routes %s through typed recovery without changing original input',
  action => {
    const original = '  checking testing\n\n'

    const recovery = [
      canonicalGestaltStream({ signal: SIGNAL_RED, service: IDENTITY_PENGUIN, evidence: ['REFUSED'] }),
      ...['Retry', 'Bypass', 'Help'].map(label => `${RELATION_ACTION} ${JSON.stringify(label)}`)
    ].join(DELIMITER_SEGMENT)

    const source = JSON.stringify({
      source: recovery,
      diagnostic: { original_input: original, recovery: { submission_id: 'failed-submission' } }
    })

    render(<DirectOperation source={source} />)
    fireEvent.click(screen.getByRole('button', { name: new RegExp(`^${action}$`, 'i') }))
    expect(mocks.submit).toHaveBeenCalledWith(action === 'help' ? 'lucid --help --modality ugui' : original, {
      target: 'main',
      penguinRecovery: { submission_id: 'failed-submission', action }
    })
  }
)

it.each(['broken', 'valid'])('keeps diagnostic copy available for %s projection', async id => {
  const copy = vi.fn<(text: string) => Promise<void>>(async () => undefined)
  vi.stubGlobal('hermesDesktop', { ...window.hermesDesktop, writeClipboard: copy })
  vi.spyOn(console, 'error').mockImplementation(() => undefined)

  const source = JSON.stringify({
    document: {
      schema: 'lucid-ugui-response/1',
      type: 'document',
      id,
      header: [],
      sections: []
    },
    diagnostic: { submission_id: 'test', receipt: { stdout: 'working tree clean' } }
  })

  render(<DirectOperation source={source} />)
  fireEvent.click(screen.getByRole('button', { name: /Copy operation diagnostics/i }))
  await waitFor(() => {
    if (id === 'broken') {
      expect(JSON.parse(copy.mock.calls[0]?.[0] ?? '{}')).toEqual({
        source,
        projection_error: 'Error: projection failed'
      })
    } else {
      expect(copy).toHaveBeenCalledWith(source)
    }
  })
  expect(screen.getByText(id === 'broken' ? 'Error: projection failed' : 'Rendered operation')).toBeTruthy()
})

it('retains malformed wire source for copying', async () => {
  const copy = vi.fn<(text: string) => Promise<void>>(async () => undefined)
  vi.stubGlobal('hermesDesktop', { ...window.hermesDesktop, writeClipboard: copy })
  render(<DirectOperation source="{invalid" />)
  fireEvent.click(screen.getByRole('button', { name: /Copy operation diagnostics/i }))
  await waitFor(() =>
    expect(JSON.parse(copy.mock.calls[0]?.[0] ?? '{}')).toMatchObject({
      source: '{invalid',
      projection_error: expect.any(String)
    })
  )
  expect(screen.getByRole('alert')).toBeTruthy()
})

it('shows processing before preparation and copies the original and transformed input', async () => {
  const copy = vi.fn<(text: string) => Promise<void>>(async () => undefined)
  vi.stubGlobal('hermesDesktop', { ...window.hermesDesktop, writeClipboard: copy })

  const preparation = (pending: boolean) =>
    JSON.stringify({
      document: { schema: 'lucid-ugui-response/1', type: 'document', id: 'preparation', header: [], sections: [] },
      diagnostic: {
        schema: 'catalyst-intent-preparation/1',
        pending,
        original_input: 'Sign in as EM',
        transformed_input: pending ? '' : 'OBJECTIVE: Sign in as EM'
      }
    })

  const view = render(<DirectOperation source={preparation(true)} />)
  expect(screen.getByText('From user / PENGUIN')).toBeTruthy()
  expect(view.container.querySelector('[aria-busy="true"]')).toBeTruthy()
  expect(screen.getByRole('status')).toBeTruthy()
  view.rerender(<DirectOperation source={preparation(false)} />)
  expect(view.container.querySelector('[aria-busy="true"]')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: /Copy operation diagnostics/i }))
  await waitFor(() => expect(copy).toHaveBeenCalledWith(preparation(false)))
})

it('projects prepared GESTALT with user/PENGUIN provenance and the full transformation copy payload', async () => {
  const copy = vi.fn<(text: string) => Promise<void>>(async () => undefined)
  vi.stubGlobal('hermesDesktop', { ...window.hermesDesktop, writeClipboard: copy })
  const transformed = canonicalGestaltStream({ signal: SIGNAL_GREEN, evidence: ['OBJECTIVE'], data: ['Sign in as EM'] })

  const source = JSON.stringify({
    document: { schema: 'lucid-ugui-response/1', type: 'document', id: 'preparation', header: [], sections: [] },
    diagnostic: {
      schema: 'catalyst-intent-preparation/1',
      phase: 'prepared',
      pending: false,
      proposal: { classification: 'semantic' },
      original_input: 'Sign in as EM',
      transformed_input: transformed
    }
  })

  const { container } = render(<DirectOperation source={source} />)
  expect(screen.getByText('From user / PENGUIN')).toBeTruthy()
  expect(container.querySelector('[data-message-origin="user-penguin"]')).toBeTruthy()
  const projection = container.querySelector('[data-preparation-projection]')
  expect(projection?.textContent).toBe(transformed)
  expect(projection?.getAttribute('data-copy-payload')).toBe(source)
  expect(projection?.getAttribute('data-continuations')).toBe('false')
  fireEvent.click(screen.getByRole('button', { name: /Copy operation diagnostics/i }))
  await waitFor(() => expect(copy).toHaveBeenCalledWith(source))
})

it('distinguishes classification from semantic preparation and retains both stages in COPY', async () => {
  const copy = vi.fn<(text: string) => Promise<void>>(async () => undefined)
  vi.stubGlobal('hermesDesktop', { ...window.hermesDesktop, writeClipboard: copy })

  const payload = (phase: string) =>
    JSON.stringify({
      document: { schema: 'lucid-ugui-response/1', type: 'document', id: 'preparation', header: [], sections: [] },
      diagnostic: {
        schema: 'catalyst-intent-preparation/1',
        pending: true,
        phase,
        classifier_response: phase === 'classification' ? null : '🔎',
        stages: [
          { stage: 'classification', system_prompt: 'classifier', response: '🔎' },
          { stage: 'semantic-preparation', system_prompt: 'GESTALT', response: null }
        ]
      }
    })

  const view = render(<DirectOperation source={payload('classification')} />)
  expect(screen.getByText('PENGUIN classifying')).toBeTruthy()
  view.rerender(<DirectOperation source={payload('semantic-preparation')} />)
  expect(screen.getByText('PENGUIN preparing GESTALT')).toBeTruthy()
  expect(screen.getByLabelText('Selected route').textContent).toBe('🔎')
  fireEvent.click(screen.getByRole('button', { name: /Copy operation diagnostics/i }))
  await waitFor(() => expect(copy).toHaveBeenCalledWith(payload('semantic-preparation')))
})

it('submits an inferred LUCID proposal only after the user activates its confirmation', () => {
  const invocation = 'lucid show --args \'{"view":"pulse"}\''

  const source = JSON.stringify({
    document: {
      schema: 'lucid-ugui-response/1',
      type: 'document',
      id: 'proposal',
      header: [],
      sections: [],
      actions: [{ value: invocation }]
    },
    diagnostic: { receipt: { refusal: 'lucid-proposal-needs-confirmation' } }
  })

  render(<DirectOperation source={source} />)
  expect(mocks.submit).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Confirm proposal' }))
  expect(mocks.submit).toHaveBeenCalledWith(invocation, expect.objectContaining({ target: expect.any(String) }))
})

it('does not enable proposal submission for an ordinary operation receipt', () => {
  const source = JSON.stringify({
    document: {
      schema: 'lucid-ugui-response/1',
      type: 'document',
      id: 'ordinary',
      header: [],
      sections: [],
      actions: [{ value: 'lucid set role' }]
    },
    diagnostic: { receipt: { ran: true } }
  })

  render(<DirectOperation source={source} />)
  fireEvent.click(screen.getByRole('button', { name: 'Confirm proposal' }))
  expect(mocks.submit).not.toHaveBeenCalled()
})
