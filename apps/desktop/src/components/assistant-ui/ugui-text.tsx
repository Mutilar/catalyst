import { useMessagePartText } from '@assistant-ui/react'
import { type ComponentProps, memo, useEffect, useState } from 'react'

import { McpUguiDocument } from '@/components/assistant-ui/tool/mcp-ugui'
import { Button } from '@/components/ui/button'
import { CopyButton } from '@/components/ui/copy-button'
import { Loader } from '@/components/ui/loader'
import { useI18n } from '@/i18n'
import { SIGNAL_RED } from '@/lib/ae-glyphs'
import type { McpUguiDocument as Document } from '@/lib/tool-presentation'
import { projectConversationText } from '@/lib/ugui-engine'

interface Projection {
  source: string
  document: Document | null
  error: string | null
}

interface UguiTextContentProps {
  containerClassName?: string
  containerProps?: ComponentProps<'div'>
  isRunning: boolean
  text: string
}

/** Source stays in the conversation runtime. Only Rust produces semantic blocks.
 * Coalesce cosmetic streaming updates; settlement projects immediately. An old
 * async result can never repaint a replacement message or an unmounted part.
 */
export function UguiTextContent({ text, isRunning, containerClassName, containerProps }: UguiTextContentProps) {
  const { t } = useI18n()
  const [projection, setProjection] = useState<Projection | null>(null)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let cancelled = false
    const project = () => {
      void projectConversationText(text, isRunning).then(
        document => {
          if (!cancelled) {setProjection({ source: text, document, error: null })}
        },
        cause => {
          if (!cancelled) {
            const error = (cause instanceof Error ? cause.message : String(cause)).slice(0, 512)
            setProjection({ source: text, document: null, error })
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
    schema: 'ugui-conversation-status/1', id: 'conversation.projection.error', type: 'document',
    header: [], actions: [],
    sections: [{ id: 'error', type: 'status', signal: SIGNAL_RED, heading: t.common.error, body: error }]
  }

  if (!text) {return null}

  return (
    <div {...containerProps} aria-busy={isRunning || !current} className={containerClassName} data-ugui-text="true">
      {error ? (
        <>
          <McpUguiDocument document={failure} presentationOnly />
          <Button onClick={() => setAttempt(value => value + 1)} size="xs" variant="text">{t.common.retry}</Button>
          <CopyButton label={t.common.copy} text={text} />
        </>
      ) : current?.document ? (
        <McpUguiDocument document={current.document} presentationOnly />
      ) : <Loader label={t.common.loading} />}
    </div>
  )
}

export const UguiText = memo(function UguiText() {
  const { text, status } = useMessagePartText()
  return <UguiTextContent isRunning={status.type === 'running'} text={text} />
})
