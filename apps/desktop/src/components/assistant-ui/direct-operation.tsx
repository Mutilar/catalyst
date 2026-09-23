import { Component, type ReactNode, useState } from 'react'

import { requestComposerSubmit } from '@/app/chat/composer/focus'
import { useComposerScope } from '@/app/chat/composer/scope'
import { McpUguiDocument } from '@/components/assistant-ui/tool/mcp-ugui'
import { UguiTextContent } from '@/components/assistant-ui/ugui-text'
import { CopyButton } from '@/components/ui/copy-button'
import { Loader } from '@/components/ui/loader'
import type { McpUguiDocument as Document } from '@/lib/tool-presentation'

class ProjectionBoundary extends Component<
  { children: ReactNode; onFailure: (error: string) => void },
  { error: string | null }
> {
  state: { error: string | null } = { error: null }

  static getDerivedStateFromError(error: unknown) {
    return { error: String(error).slice(0, 512) }
  }

  componentDidCatch(error: unknown) {
    this.props.onFailure(String(error).slice(0, 512))
  }

  render() {
    if (this.state.error) {
      return (
        <div className="text-destructive whitespace-pre-wrap" role="alert">
          {this.state.error}
        </div>
      )
    }

    return this.props.children
  }
}

export function DirectOperation({ source }: { source: string }) {
  const { target } = useComposerScope()
  const [failure, setFailure] = useState<{ source: string; error: string } | null>(null)
  let document: Document | null = null
  let semanticSource: string | null = null
  let error: string | null = null
  let processing = false
  let processingLabel = 'PENGUIN processing'
  let classifierGlyph: string | null = null
  let preparation = false
  let gestalt: string | null = null
  let confirmProposal = false
  let recovery: { submission_id: string; original: string } | null = null

  try {
    const value: unknown = JSON.parse(source)

    if (!value || typeof value !== 'object') {
      throw new Error('Direct operation document missing')
    }

    if ('source' in value && typeof value.source === 'string' && value.source.length > 0) {
      semanticSource = value.source
    } else if ('document' in value) {
      document = value.document as Document
    }

    if (
      'diagnostic' in value &&
      value.diagnostic &&
      typeof value.diagnostic === 'object' &&
      'recovery' in value.diagnostic &&
      value.diagnostic.recovery &&
      typeof value.diagnostic.recovery === 'object' &&
      'submission_id' in value.diagnostic.recovery &&
      typeof value.diagnostic.recovery.submission_id === 'string' &&
      'original_input' in value.diagnostic &&
      typeof value.diagnostic.original_input === 'string'
    ) {
      recovery = { submission_id: value.diagnostic.recovery.submission_id, original: value.diagnostic.original_input }
    }

    if (
      'diagnostic' in value &&
      value.diagnostic &&
      typeof value.diagnostic === 'object' &&
      'receipt' in value.diagnostic &&
      value.diagnostic.receipt &&
      typeof value.diagnostic.receipt === 'object' &&
      'refusal' in value.diagnostic.receipt
    ) {
      confirmProposal = value.diagnostic.receipt.refusal === 'lucid-proposal-needs-confirmation'
    }

    if (
      'diagnostic' in value &&
      value.diagnostic &&
      typeof value.diagnostic === 'object' &&
      'schema' in value.diagnostic &&
      value.diagnostic.schema === 'catalyst-intent-preparation/1'
    ) {
      preparation = true
      processing = 'pending' in value.diagnostic && value.diagnostic.pending === true
      const diagnostic = value.diagnostic

      if (
        'classifier_response' in diagnostic &&
        typeof diagnostic.classifier_response === 'string' &&
        ['🧠', '🔎', '🤖'].includes(diagnostic.classifier_response.trim())
      ) {
        classifierGlyph = diagnostic.classifier_response.trim()
      }

      if ('phase' in diagnostic) {
        if (diagnostic.phase === 'classification') {
          processingLabel = 'PENGUIN classifying'
        }

        if (diagnostic.phase === 'semantic-preparation') {
          processingLabel = 'PENGUIN preparing GESTALT'
        }

        if (diagnostic.phase === 'lucid-preparation') {
          processingLabel = 'PENGUIN formatting LUCID'
        }

        if (diagnostic.phase === 'lucid-verb') {
          processingLabel = 'PENGUIN selecting a verb'
        }

        if (diagnostic.phase === 'lucid-noun') {
          processingLabel = 'PENGUIN selecting a target'
        }

        if (
          diagnostic.phase === 'lucid-optional' ||
          (typeof diagnostic.phase === 'string' && diagnostic.phase.startsWith('lucid-argument:'))
        ) {
          processingLabel = 'PENGUIN resolving arguments'
        }

        if (diagnostic.phase === 'execution') {
          processingLabel = 'Executing request'
        }
      }

      if (
        'phase' in diagnostic &&
        diagnostic.phase === 'prepared' &&
        'proposal' in diagnostic &&
        diagnostic.proposal &&
        typeof diagnostic.proposal === 'object' &&
        'classification' in diagnostic.proposal &&
        diagnostic.proposal.classification === 'semantic' &&
        'transformed_input' in diagnostic &&
        typeof diagnostic.transformed_input === 'string' &&
        diagnostic.transformed_input.length > 0
      ) {
        gestalt = diagnostic.transformed_input
      }
    }

    if (
      semanticSource === null &&
      (document?.schema !== 'lucid-ugui-response/1' || !['document', 'lucid'].includes(document.type))
    ) {
      throw new Error('Direct operation document invalid')
    }
  } catch (cause) {
    error = String(cause).slice(0, 512)
  }

  const projectionError = error ?? (failure?.source === source ? failure.error : null)
  const copyPayload = projectionError ? JSON.stringify({ source, projection_error: projectionError }) : source
  const recoveryRequest = recovery

  const onContinuation = recoveryRequest
    ? (label: string) => {
        const action = label.toLowerCase()

        if (action === 'retry' || action === 'bypass' || action === 'help') {
          requestComposerSubmit(action === 'help' ? 'lucid --help --modality ugui' : recoveryRequest.original, {
            target,
            penguinRecovery: { submission_id: recoveryRequest.submission_id, action }
          })
        }
      }
    : confirmProposal
      ? (text: string) => requestComposerSubmit(text, { target })
      : undefined

  return (
    <div
      aria-busy={processing}
      className="w-full min-w-0 space-y-2"
      data-direct-operation="true"
      data-message-origin={preparation ? 'user-penguin' : 'user-operation'}
    >
      {preparation && <div className="text-xs font-medium text-muted-foreground">From user / PENGUIN</div>}
      {classifierGlyph && (
        <div aria-label="Selected route" className="text-xs text-muted-foreground">
          {classifierGlyph}
        </div>
      )}
      {processing && (
        <div aria-live="polite" className="flex items-center gap-2">
          <Loader label={processingLabel} role="status" />
          <span>{processingLabel}</span>
        </div>
      )}
      <CopyButton appearance="inline" label="Copy operation diagnostics" showLabel text={copyPayload} />
      {error ? (
        <div className="text-destructive" role="alert">
          {error}
        </div>
      ) : (
        <ProjectionBoundary key={source} onFailure={error => setFailure({ source, error })}>
          {gestalt !== null ? (
            <UguiTextContent allowContinuations={false} copyText={copyPayload} isRunning={false} text={gestalt} />
          ) : semanticSource !== null ? (
            <UguiTextContent
              allowContinuations={Boolean(onContinuation)}
              copyText={copyPayload}
              isRunning={processing}
              onContinuation={onContinuation}
              text={semanticSource}
            />
          ) : (
            document && (
              <McpUguiDocument
                copyText={copyPayload}
                document={document}
                onContinuation={onContinuation}
                presentationOnly
              />
            )
          )}
        </ProjectionBoundary>
      )}
    </div>
  )
}
