import { useMessagePartText } from '@assistant-ui/react'
import { type ComponentProps, memo, useCallback, useEffect, useState } from 'react'

import { requestComposerSubmit } from '@/app/chat/composer/focus'
import { useComposerScope } from '@/app/chat/composer/scope'
import { McpUguiDocument } from '@/components/assistant-ui/tool/mcp-ugui'
import { Button } from '@/components/ui/button'
import { Loader } from '@/components/ui/loader'
import { useI18n } from '@/i18n'
import { SIGNAL_RED } from '@/lib/ae-glyphs'
import type { McpUguiDocument as Document } from '@/lib/tool-presentation'
import { type ConversationProjection, projectConversationText } from '@/lib/ugui-engine'
import { cn } from '@/lib/utils'

interface Projection {
  source: string
  documents: ConversationProjection['documents'] | null
  error: string | null
}

interface UguiTextContentProps {
  containerClassName?: string
  containerProps?: ComponentProps<'div'>
  isRunning: boolean
  text: string
  copyText?: string
  allowContinuations?: boolean
  onContinuation?: (text: string) => void
}

/** Source stays in the conversation runtime. Only Rust produces semantic blocks.
 * Coalesce cosmetic streaming updates; settlement projects immediately. An old
 * async result can never repaint a replacement message or an unmounted part.
 */
export function UguiTextContent({ text, isRunning, containerClassName, containerProps, copyText, allowContinuations = true, onContinuation }: UguiTextContentProps) {
  const { t } = useI18n()
  const { target } = useComposerScope()

  const submitContinuation = useCallback((prompt: string) => {
    requestComposerSubmit(prompt, { target })
  }, [target])

  const [projection, setProjection] = useState<Projection | null>(null)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let cancelled = false

    const project = () => {
      void projectConversationText(text, isRunning).then(
        result => {
          if (!cancelled) {setProjection({ source: text, documents: result.documents, error: null })}
        },
        cause => {
          if (!cancelled) {
            const error = (cause instanceof Error ? cause.message : String(cause)).slice(0, 512)
            setProjection({ source: text, documents: null, error })
          }
        }
      )
    }

    const frame = isRunning ? requestAnimationFrame(project) : null

    if (!isRunning) {project()}

    return () => {
      cancelled = true

      if (frame !== null) {cancelAnimationFrame(frame)}
    }
  }, [text, isRunning, attempt])

  // Append-only updates may retain the last projection for one frame. Replacement
  // text must not display a previous message's document, even before effects run.
  const current = projection && text.startsWith(projection.source) ? projection : null
  const error = current?.source === text ? current.error : null

  const failure: Document = {
    schema: 'lucid-ugui-response/1', id: 'conversation.projection.error', type: 'document',
    header: [], actions: [],
    sections: [{ id: 'error', type: 'status', signal: SIGNAL_RED, heading: t.common.error, body: error }]
  }

  if (!text) {return null}

  return (
    <div {...containerProps} aria-busy={isRunning || !current} className={cn('min-w-0 w-full max-w-full space-y-2', containerClassName)} data-ugui-text="true">
      {error ? (
        <>
          <McpUguiDocument copyText={copyText ?? text} document={failure} presentationOnly />
          <Button onClick={() => setAttempt(value => value + 1)} size="xs" variant="text">{t.common.retry}</Button>
        </>
      ) : current?.documents ? current.documents.map(document => (
        <ParagraphDocument copyText={copyText} document={document} key={document.id} onContinuation={allowContinuations ? onContinuation ?? submitContinuation : undefined} />
      )) : <Loader label={t.common.loading} />}
    </div>
  )
}

const ParagraphDocument = memo(function ParagraphDocument({ document, onContinuation, copyText }: {
  document: ConversationProjection['documents'][number]
  onContinuation?: (text: string) => void
  copyText?: string
}) {
  return <McpUguiDocument copyText={copyText ?? document.source} document={document} onContinuation={onContinuation} presentationOnly />
}, (before, after) => before.document.id === after.document.id && before.document.revision === after.document.revision && before.onContinuation === after.onContinuation && before.copyText === after.copyText)

export const UguiText = memo(function UguiText() {
  const { text, status } = useMessagePartText()

  return <UguiTextContent isRunning={status.type === 'running'} text={text} />
})
