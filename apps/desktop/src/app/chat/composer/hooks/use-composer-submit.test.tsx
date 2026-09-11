import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { ComposerAttachment } from '@/store/composer'

import { useComposerSubmit } from './use-composer-submit'

interface SubmitHarnessOptions {
  attachments?: ComposerAttachment[]
  busy?: boolean
  compacting?: boolean
  text?: string
}

function renderSubmitHook({
  attachments = [],
  busy = false,
  compacting = false,
  text = ''
}: SubmitHarnessOptions = {}) {
  const draftRef = { current: text }
  const editor = document.createElement('div')
  editor.dataset.slot = 'composer-rich-input'
  editor.textContent = text
  const editorRef = { current: editor }
  const onCancel = vi.fn()
  const onSteer = vi.fn(async () => true)
  const onSubmit = vi.fn(async () => true)
  const queueCurrentDraft = vi.fn(() => true)

  const clearDraft = vi.fn(() => {
    draftRef.current = ''
    editorRef.current!.textContent = ''
  })

  const hook = renderHook(() =>
    useComposerSubmit({
      activeQueueSessionKey: 'stored-session',
      activeQueueSessionKeyRef: { current: 'stored-session' },
      attachments,
      busy,
      compacting,
      clearDraft,
      disabled: false,
      draftRef,
      drainNextQueued: vi.fn(async () => false),
      editorRef,
      exitQueuedEdit: vi.fn(() => false),
      focusInput: vi.fn(),
      inputDisabled: false,
      loadIntoComposer: vi.fn(),
      onCancel,
      onSteer,
      onSubmit,
      queueCurrentDraft,
      queueEdit: null,
      queuedPrompts: [],
      sessionId: 'runtime-session',
      setComposerText: vi.fn(),
      stashAt: vi.fn()
    })
  )

  return { clearDraft, hook, onCancel, onSteer, onSubmit, queueCurrentDraft }
}

describe('useComposerSubmit busy-turn routing', () => {
  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
  })

  it('submits busy plain-text input to shared admission without steering', async () => {
    const { hook, onCancel, onSteer, onSubmit, queueCurrentDraft } = renderSubmitHook({
      busy: true,
      text: 'change course'
    })

    act(() => {
      hook.result.current.submitDraft()
    })

    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith('change course', { attachments: [] }))
    expect(queueCurrentDraft).not.toHaveBeenCalled()
    expect(onCancel).not.toHaveBeenCalled()
    expect(onSteer).not.toHaveBeenCalled()
  })

  it('submits input for admission while the active turn is compacting', () => {
    const { hook, onCancel, onSteer, onSubmit, queueCurrentDraft } = renderSubmitHook({
      busy: true,
      compacting: true,
      text: 'wait for the summary'
    })

    act(() => {
      hook.result.current.submitDraft()
    })

    expect(queueCurrentDraft).not.toHaveBeenCalled()
    expect(onSteer).not.toHaveBeenCalled()
    expect(onSubmit).toHaveBeenCalledWith('wait for the summary', { attachments: [] })
    expect(onCancel).not.toHaveBeenCalled()
  })

  it('runs slash commands immediately while busy', async () => {
    const { clearDraft, hook, onCancel, onSteer, onSubmit, queueCurrentDraft } = renderSubmitHook({
      busy: true,
      text: '/compress preserve context'
    })

    act(() => {
      hook.result.current.submitDraft()
    })

    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith('/compress preserve context'))
    expect(clearDraft).toHaveBeenCalledTimes(1)
    expect(onSteer).not.toHaveBeenCalled()
    expect(queueCurrentDraft).not.toHaveBeenCalled()
    expect(onCancel).not.toHaveBeenCalled()
  })

  it('submits attachment-bearing input for admission while busy', () => {
    const attachment: ComposerAttachment = { id: 'doc', kind: 'file', label: 'notes.txt' }

    const { hook, onCancel, onSteer, onSubmit, queueCurrentDraft } = renderSubmitHook({
      attachments: [attachment],
      busy: true,
      text: 'read this'
    })

    act(() => {
      hook.result.current.submitDraft()
    })

    expect(queueCurrentDraft).not.toHaveBeenCalled()
    expect(onSteer).not.toHaveBeenCalled()
    expect(onSubmit).toHaveBeenCalledWith('read this', { attachments: [attachment] })
    expect(onCancel).not.toHaveBeenCalled()
  })

  it('submits image-bearing input for admission instead of steering', async () => {
    const image: ComposerAttachment = { id: 'shot', kind: 'image', label: 'screen.png', path: '/tmp/screen.png' }

    const { hook, onSubmit, onSteer, queueCurrentDraft } = renderSubmitHook({
      attachments: [image],
      busy: true,
      text: 'look at this'
    })

    act(() => {
      hook.result.current.submitDraft()
    })

    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith('look at this', { attachments: [image] }))
    expect(onSteer).not.toHaveBeenCalled()
    expect(queueCurrentDraft).not.toHaveBeenCalled()
  })

  it('preserves mixed attachments through shared admission', () => {
    const image: ComposerAttachment = { id: 'shot', kind: 'image', label: 'screen.png' }
    const doc: ComposerAttachment = { id: 'doc', kind: 'file', label: 'notes.txt' }

    const { hook, onSubmit, onSteer, queueCurrentDraft } = renderSubmitHook({
      attachments: [image, doc],
      busy: true,
      text: 'read both'
    })

    act(() => {
      hook.result.current.submitDraft()
    })

    expect(queueCurrentDraft).not.toHaveBeenCalled()
    expect(onSubmit).toHaveBeenCalledWith('read both', { attachments: [image, doc] })
    expect(onSteer).not.toHaveBeenCalled()
  })

  it('stops an active turn only with an empty composer', () => {
    const { hook, onCancel, onSteer, onSubmit, queueCurrentDraft } = renderSubmitHook({ busy: true })

    act(() => {
      hook.result.current.submitDraft()
    })

    expect(onCancel).toHaveBeenCalledTimes(1)
    expect(onSteer).not.toHaveBeenCalled()
    expect(onSubmit).not.toHaveBeenCalled()
    expect(queueCurrentDraft).not.toHaveBeenCalled()
  })

  it('submits a normal turn while idle', async () => {
    const { hook, onCancel, onSteer, onSubmit, queueCurrentDraft } = renderSubmitHook({ text: 'ordinary question' })

    act(() => {
      hook.result.current.submitDraft()
    })

    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith('ordinary question', { attachments: [] }))
    expect(onSteer).not.toHaveBeenCalled()
    expect(queueCurrentDraft).not.toHaveBeenCalled()
    expect(onCancel).not.toHaveBeenCalled()
  })
})
