import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import { DirectOperation } from './direct-operation'

vi.mock('@/components/assistant-ui/ugui-text', () => ({
  UguiTextContent: ({ text, copyText, allowContinuations }: { text: string; copyText: string; allowContinuations: boolean }) => (
    <div data-preparation-projection="true" data-copy-payload={copyText} data-continuations={String(allowContinuations)}>{text}</div>
  )
}))

vi.mock('@/components/assistant-ui/tool/mcp-ugui', () => ({
  McpUguiDocument: ({ document }: { document: { id: string } }) => {
    if (document.id === 'broken') {throw new Error('projection failed')}
    return <div>Rendered operation</div>
  }
}))

afterEach(() => {cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals()})

it.each(['broken', 'valid'])('keeps diagnostic copy available for %s projection', async id => {
  const copy = vi.fn<(text: string) => Promise<void>>(async () => undefined)
  vi.stubGlobal('hermesDesktop', { ...window.hermesDesktop, writeClipboard: copy })
  vi.spyOn(console, 'error').mockImplementation(() => undefined)
  const source = JSON.stringify({ document: {
    schema: 'lucid-ugui-response/1', type: 'document', id, header: [], sections: []
  }, diagnostic: { submission_id: 'test', receipt: { stdout: 'working tree clean' } } })
  render(<DirectOperation source={source} />)
  fireEvent.click(screen.getByRole('button', { name: /Copy operation diagnostics/i }))
  await waitFor(() => {
    if (id === 'broken') {
      expect(JSON.parse(copy.mock.calls[0]?.[0] ?? '{}')).toEqual({ source, projection_error: 'Error: projection failed' })
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
  await waitFor(() => expect(JSON.parse(copy.mock.calls[0]?.[0] ?? '{}')).toMatchObject({ source: '{invalid', projection_error: expect.any(String) }))
  expect(screen.getByRole('alert')).toBeTruthy()
})

it('shows processing before preparation and copies the original and transformed input', async () => {
  const copy = vi.fn<(text: string) => Promise<void>>(async () => undefined)
  vi.stubGlobal('hermesDesktop', { ...window.hermesDesktop, writeClipboard: copy })
  const preparation = (pending: boolean) => JSON.stringify({
    document: { schema: 'lucid-ugui-response/1', type: 'document', id: 'preparation', header: [], sections: [] },
    diagnostic: { schema: 'catalyst-intent-preparation/1', pending,
      original_input: 'Sign in as EM', transformed_input: pending ? '' : 'OBJECTIVE: Sign in as EM' }
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
  const transformed = '🟢 · 🧠 · 🔎 OBJECTIVE · ◆ Sign in as EM'
  const source = JSON.stringify({
    document: { schema: 'lucid-ugui-response/1', type: 'document', id: 'preparation', header: [], sections: [] },
    diagnostic: { schema: 'catalyst-intent-preparation/1', phase: 'prepared', pending: false,
      proposal: { classification: 'semantic' }, original_input: 'Sign in as EM', transformed_input: transformed }
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
  const payload = (phase: string) => JSON.stringify({
    document: { schema: 'lucid-ugui-response/1', type: 'document', id: 'preparation', header: [], sections: [] },
    diagnostic: { schema: 'catalyst-intent-preparation/1', pending: true, phase,
      classifier_response: phase === 'classification' ? null : '🔎',
      stages: [{ stage: 'classification', system_prompt: 'classifier', response: '🔎' },
        { stage: 'semantic-preparation', system_prompt: 'GESTALT', response: null }] }
  })
  const view = render(<DirectOperation source={payload('classification')} />)
  expect(screen.getByText('PENGUIN classifying')).toBeTruthy()
  view.rerender(<DirectOperation source={payload('semantic-preparation')} />)
  expect(screen.getByText('PENGUIN preparing GESTALT')).toBeTruthy()
  expect(screen.getByLabelText('Selected route').textContent).toBe('🔎')
  fireEvent.click(screen.getByRole('button', { name: /Copy operation diagnostics/i }))
  await waitFor(() => expect(copy).toHaveBeenCalledWith(payload('semantic-preparation')))
})