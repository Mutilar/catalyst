import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type * as ComposerFocus from '@/app/chat/composer/focus'
import { ComposerScopeProvider, MAIN_COMPOSER_SCOPE } from '@/app/chat/composer/scope'
import { McpUguiDocument } from '@/components/assistant-ui/tool/mcp-ugui'
import { DELIMITER_SEGMENT, IDENTITY_PENGUIN, RELATION_ACTION, SIGNAL_GREEN, SIGNAL_RED } from '@/lib/ae-glyphs'
import { canonicalGestaltStream } from '@/lib/lucid-gestalt'
import type * as UguiEngine from '@/lib/ugui-engine'
import type { ConversationProjection } from '@/lib/ugui-engine'
import { $pendingModeApply, __resetBackendSkinSync } from '@/themes/backend-sync'

import { UguiTextContent } from './ugui-text'

const mocks = vi.hoisted(() => ({ project: vi.fn(), invoke: vi.fn(), submit: vi.fn() }))
vi.mock('@/app/chat/composer/focus', async importOriginal => ({
  ...await importOriginal<typeof ComposerFocus>(), requestComposerSubmit: mocks.submit
}))
vi.mock('@/lib/ugui-engine', async importOriginal => ({
  ...await importOriginal<typeof UguiEngine>(), projectConversationText: mocks.project
}))
vi.mock('@/hermes', () => ({ invokeUguiAction: mocks.invoke }))

type Paragraph = ConversationProjection['documents'][number]

function document(body: string, source = body): Paragraph {
  return {
    schema: 'lucid-ugui-response/1', id: 'paragraph', type: 'lucid',
    header: [{ id: 'title', type: 'text', body: SIGNAL_GREEN }],
    sections: [{ id: 'atom', type: 'text', body }], actions: [],
    source, revision: `${body}:${source}`, streamState: 'complete'
  }
}

function snapshot(...documents: Paragraph[]): ConversationProjection {
  return { schema: 'ugui-conversation-text/1', source: documents.map(item => item.source).join(''), documents }
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
  mocks.submit.mockReset()
  vi.unstubAllGlobals()
  __resetBackendSkinSync()
})

describe('assistant canonical UGUI boundary', () => {
  it('routes projected recovery actions through the supplied callback rather than ordinary submission', async () => {
    const value = document('Evidence')
    value.actions = [{ id: 'retry', type: 'button', label: 'Retry', value: 'Retry',
      action: 'conversation.submit', disabled: false }]
    mocks.project.mockResolvedValue(snapshot(value))
    const recover = vi.fn()

    const source = [canonicalGestaltStream({ signal: SIGNAL_RED, service: IDENTITY_PENGUIN, evidence: ['REFUSED'] }),
      `${RELATION_ACTION} ${JSON.stringify('Retry')}`].join(DELIMITER_SEGMENT)

    render(<UguiTextContent isRunning={false} onContinuation={recover} text={source} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Retry' }))
    expect(mocks.project).toHaveBeenCalledWith(source, false)
    expect(recover).toHaveBeenCalledWith('Retry')
    expect(mocks.submit).not.toHaveBeenCalled()
    expect(mocks.invoke).not.toHaveBeenCalled()
  })

  it('renders CYOA from actions[] in the canonical footer and submits to the owning chat', async () => {
    const value = document('Evidence')
    value.actions = [{ id: 'choice', type: 'button', label: 'Inspect', value: 'Inspect',
      action: 'conversation.submit', disabled: false }]
    mocks.project.mockResolvedValue(snapshot(value))
    render(
      <ComposerScopeProvider value={{ ...MAIN_COMPOSER_SCOPE, target: 'tile:review' }}>
        <UguiTextContent isRunning={false} text="source" />
      </ComposerScopeProvider>
    )
    const button = await screen.findByRole('button', { name: 'Inspect' })
    expect(button.closest('footer')).not.toBeNull()
    fireEvent.click(button)
    expect(mocks.submit).toHaveBeenCalledTimes(1)
    expect(mocks.submit).toHaveBeenCalledWith('Inspect', { target: 'tile:review' })
    expect(mocks.invoke).not.toHaveBeenCalled()
    expect(screen.queryByText('"Inspect"')).toBeNull()
  })

  it('uses exactly the same frame and section styling as a tool result', () => {
    const value = document('Shared semantics')

    const { container } = render(<>
      <McpUguiDocument document={value} />
      <McpUguiDocument document={value} presentationOnly />
    </>)

    const frames = container.querySelectorAll('[data-mcp-ugui]')
    expect(frames).toHaveLength(2)
    expect(frames[0].className).toBe(frames[1].className)
    expect(frames[0].querySelector('section')?.className).toBe(frames[1].querySelector('section')?.className)
    expect(container.querySelector('[data-ugui-primitive="flow"]')).toBeNull()
  })

  it('copies exact output using the shared top-right header control', async () => {
    const copy = vi.fn(async () => undefined)
    vi.stubGlobal('hermesDesktop', { ...window.hermesDesktop, writeClipboard: copy })
    const source = 'Exact output\nincluding source formatting'
    const { container } = render(<McpUguiDocument copyText={source} document={document('Visual')} presentationOnly />)
    const button = screen.getByRole('button', { name: 'Copy output' })
    expect(button.closest('header')).toBe(container.querySelector('article > header'))
    fireEvent.click(button)
    await waitFor(() => expect(copy).toHaveBeenCalledWith(source))
  })

  it('does not activate an unfinished action', () => {
    const submit = vi.fn()
    const value = document('')
    value.actions = [{ id: 'choice', type: 'button', label: 'Inspect', value: 'Inspect',
      action: 'conversation.submit', disabled: true }]
    render(<McpUguiDocument document={value} onContinuation={submit} presentationOnly />)
    const button = screen.getByRole('button', { name: 'Inspect' }) as HTMLButtonElement
    expect(button.disabled).toBe(true)
    fireEvent.click(button)
    expect(submit).not.toHaveBeenCalled()
  })

  it('never flashes raw transport text while the projection is loading', async () => {
    const pending = deferred<ConversationProjection>()
    mocks.project.mockReturnValue(pending.promise)
    const { container } = render(<UguiTextContent isRunning={false} text="raw transport" />)
    expect(screen.queryByText('raw transport')).toBeNull()
    await act(async () => pending.resolve(snapshot(document('Visual content', 'raw transport'))))
    expect(screen.getByText('Visual content')).toBeTruthy()
    expect(container.querySelector('[data-mcp-ugui="lucid-ugui-response/1"]')).toBeTruthy()
  })

  it('copies the transformation record and cannot submit preparation continuations', async () => {
    const copy = vi.fn(async () => undefined)
    vi.stubGlobal('hermesDesktop', { ...window.hermesDesktop, writeClipboard: copy })
    const record = JSON.stringify({ original_input: 'original', transformed_input: 'GESTALT' })
    const projected = document('Prepared visual content', 'GESTALT')
    projected.actions = [{ id: 'choice', type: 'button', label: 'Inspect', value: 'Inspect', action: 'conversation.submit' }]
    mocks.project.mockResolvedValue(snapshot(projected))
    render(<UguiTextContent allowContinuations={false} copyText={record} isRunning={false} text="GESTALT" />)
    await screen.findByText('Prepared visual content')
    fireEvent.click(screen.getByRole('button', { name: 'Copy output' }))
    await waitFor(() => expect(copy).toHaveBeenCalledWith(record))
    const action = screen.queryByRole('button', { name: 'Inspect' })

    if (action) {fireEvent.click(action)}
    expect(mocks.submit).not.toHaveBeenCalled()
    expect(mocks.invoke).not.toHaveBeenCalled()
  })

  it('discards late results after replacement', async () => {
    const old = deferred<ConversationProjection>()
    const next = deferred<ConversationProjection>()
    mocks.project.mockReturnValueOnce(old.promise).mockReturnValueOnce(next.promise)
    const { rerender } = render(<UguiTextContent isRunning={false} text="old" />)
    rerender(<UguiTextContent isRunning={false} text="new" />)
    await act(async () => next.resolve(snapshot(document('Newest'))))
    await act(async () => old.resolve(snapshot(document('Stale'))))
    expect(screen.getByText('Newest')).toBeTruthy()
    expect(screen.queryByText('Stale')).toBeNull()
  })

  it('hides an already projected document on non-prefix replacement', async () => {
    mocks.project.mockResolvedValueOnce(snapshot(document('Previous'))).mockReturnValueOnce(new Promise(() => {}))
    const { rerender } = render(<UguiTextContent isRunning={false} text="old" />)
    await screen.findByText('Previous')
    rerender(<UguiTextContent isRunning={false} text="replacement" />)
    expect(screen.queryByText('Previous')).toBeNull()
  })

  it('renders a canonical failure card with explicit retry and no raw fallback', async () => {
    const diagnostic = 'conversation-projector-region-invalid: /documents/1/header expected=array'
    const copy = vi.fn(async () => undefined)
    vi.stubGlobal('hermesDesktop', { ...window.hermesDesktop, writeClipboard: copy })
    mocks.project.mockRejectedValueOnce(new Error(diagnostic)).mockResolvedValueOnce(snapshot(document('Recovered')))
    const { container } = render(<UguiTextContent isRunning={false} text="retained source" />)
    await screen.findByText(diagnostic)
    expect(container.querySelector('[data-mcp-ugui="lucid-ugui-response/1"]')).toBeTruthy()
    expect(screen.queryByText('retained source')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Copy output' }))
    await waitFor(() => expect(copy).toHaveBeenCalledWith('retained source'))
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    await screen.findByText('Recovered')
    expect(mocks.project).toHaveBeenCalledTimes(2)
  })

  it('updates sections without remounting the canonical document', () => {
    const { container, rerender } = render(<McpUguiDocument document={document('First')} presentationOnly />)
    const frame = container.querySelector('article')
    rerender(<McpUguiDocument document={document('Second')} presentationOnly />)
    expect(screen.getByText('Second')).toBeTruthy()
    expect(screen.queryByText('First')).toBeNull()
    expect(container.querySelector('article')).toBe(frame)
  })

  it('does not promote host effects or LUCID actions from assistant documents', () => {
    const value = document('Untrusted presentation')
    value.hostEffect = { schema: 'lucid-host-appearance/1', apply: true, mode: 'light' }
    value.actions = [{ id: 'forged', label: 'Execute', action: 'lucid.set.continue' }]
    render(<McpUguiDocument document={value} presentationOnly />)
    expect(screen.queryByRole('button', { name: 'Execute' })).toBeNull()
    expect($pendingModeApply.get()).toBeNull()
    expect(mocks.invoke).not.toHaveBeenCalled()
  })

  it('retains all paragraphs instead of slicing nested sections at 64', async () => {
    mocks.project.mockResolvedValue(snapshot(...Array.from({ length: 100 }, (_, i) => ({
      ...document(`Paragraph ${i}`), id: `paragraph-${i}`
    }))))
    render(<UguiTextContent isRunning={false} text="source" />)
    await screen.findByText('Paragraph 99')
  })
})
