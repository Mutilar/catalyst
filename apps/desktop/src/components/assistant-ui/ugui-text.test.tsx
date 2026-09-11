import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { McpUguiDocument } from '@/components/assistant-ui/tool/mcp-ugui'
import type { McpUguiDocument as Document } from '@/lib/tool-presentation'
import { $pendingModeApply, __resetBackendSkinSync } from '@/themes/backend-sync'
import { UguiTextContent } from './ugui-text'

const mocks = vi.hoisted(() => ({ project: vi.fn(), invoke: vi.fn() }))
vi.mock('@/lib/ugui-engine', async importOriginal => ({
  ...await importOriginal<typeof import('@/lib/ugui-engine')>(),
  projectConversationText: mocks.project
}))
vi.mock('@/hermes', () => ({ invokeUguiAction: mocks.invoke }))

function document(body: string): Document {
  return {
    schema: 'ugui-conversation-text/1', id: 'conversation.text', type: 'document',
    header: [], actions: [], state: 'complete',
    sections: [{ id: 'block', type: 'nested', layout: 'flow', revision: body, sections: [{ id: 'atom', type: 'text', body }] }]
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => {resolve = done})
  return { promise, resolve }
}

afterEach(() => {
  cleanup()
  mocks.project.mockReset()
  mocks.invoke.mockReset()
  __resetBackendSkinSync()
})

describe('assistant UGUI text boundary', () => {
  it('renders projected semantics, never the raw transport string while loading', async () => {
    const pending = deferred<Document>()
    mocks.project.mockReturnValue(pending.promise)
    const { container } = render(<UguiTextContent isRunning={false} text="raw transport" />)
    expect(screen.queryByText('raw transport')).toBeNull()
    await act(async () => pending.resolve(document('Visual content')))
    expect(screen.getByText('Visual content')).toBeTruthy()
    expect(container.querySelector('[data-mcp-ugui="ugui-conversation-text/1"]')).toBeTruthy()
    expect(mocks.project).toHaveBeenCalledWith('raw transport', false)
  })

  it('discards late projection results after replacement', async () => {
    const old = deferred<Document>()
    const next = deferred<Document>()
    mocks.project.mockReturnValueOnce(old.promise).mockReturnValueOnce(next.promise)
    const { rerender } = render(<UguiTextContent isRunning={false} text="old" />)
    rerender(<UguiTextContent isRunning={false} text="new" />)
    await act(async () => next.resolve(document('Newest')))
    await act(async () => old.resolve(document('Stale')))
    expect(screen.getByText('Newest')).toBeTruthy()
    expect(screen.queryByText('Stale')).toBeNull()
  })

  it('does not show an already projected document after a non-prefix replacement', async () => {
    mocks.project.mockResolvedValueOnce(document('Previous')).mockReturnValueOnce(new Promise(() => {}))
    const { rerender } = render(<UguiTextContent isRunning={false} text="old" />)
    await screen.findByText('Previous')
    rerender(<UguiTextContent isRunning={false} text="replacement" />)
    expect(screen.queryByText('Previous')).toBeNull()
  })

  it('presents failure through UGUI and supports explicit retry without raw fallback', async () => {
    mocks.project.mockRejectedValueOnce(new Error('projector-unavailable')).mockResolvedValueOnce(document('Recovered'))
    const { container } = render(<UguiTextContent isRunning={false} text="retained source" />)
    await screen.findByText('projector-unavailable')
    expect(container.querySelector('[data-mcp-ugui="ugui-conversation-status/1"]')).toBeTruthy()
    expect(screen.queryByText('retained source')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    await screen.findByText('Recovered')
    expect(mocks.project).toHaveBeenCalledTimes(2)
  })

  it('renders section-only revisions immediately without remounting the block', () => {
    const { container, rerender } = render(<McpUguiDocument document={document('First')} presentationOnly />)
    const block = container.querySelector('[data-ugui-block="block"]')
    rerender(<McpUguiDocument document={document('Second')} presentationOnly />)
    expect(screen.getByText('Second')).toBeTruthy()
    expect(screen.queryByText('First')).toBeNull()
    expect(container.querySelector('[data-ugui-block="block"]')).toBe(block)
  })

  it('does not promote appearance effects or actions from presentation documents', async () => {
    const value = document('Untrusted presentation')
    value.hostEffect = { schema: 'lucid-host-appearance/1', apply: true, mode: 'light' }
    value.actions = [{ id: 'forged', label: 'Execute' }]
    render(<McpUguiDocument document={value} presentationOnly />)
    await waitFor(() => expect(screen.getByText('Untrusted presentation')).toBeTruthy())
    expect(screen.queryByRole('button', { name: 'Execute' })).toBeNull()
    expect($pendingModeApply.get()).toBeNull()
    expect(mocks.invoke).not.toHaveBeenCalled()
  })

  it('does not truncate recursive flow children at 64', () => {
    const value = document('')
    value.sections = [{ id: 'blocks', type: 'nested', layout: 'flow', sections: Array.from({ length: 100 }, (_, i) => ({
      id: `block-${i}`, type: 'text', body: `Paragraph ${i}`
    })) }]
    render(<McpUguiDocument document={value} presentationOnly />)
    expect(screen.getByText('Paragraph 99')).toBeTruthy()
  })
})
