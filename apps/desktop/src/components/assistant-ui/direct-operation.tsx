import { Component, type ReactNode, useState } from 'react'

import { McpUguiDocument } from '@/components/assistant-ui/tool/mcp-ugui'
import { UguiTextContent } from '@/components/assistant-ui/ugui-text'
import { CopyButton } from '@/components/ui/copy-button'
import { Loader } from '@/components/ui/loader'
import type { McpUguiDocument as Document } from '@/lib/tool-presentation'

class ProjectionBoundary extends Component<{ children: ReactNode; onFailure: (error: string) => void }, { error: string | null }> {
  state: { error: string | null } = { error: null }

  static getDerivedStateFromError(error: unknown) {
    return { error: String(error).slice(0, 512) }
  }

  componentDidCatch(error: unknown) {
    this.props.onFailure(String(error).slice(0, 512))
  }

  render() {
    if (this.state.error) {
      return <div role="alert" className="text-destructive whitespace-pre-wrap">{this.state.error}</div>
    }
    return this.props.children
  }
}

export function DirectOperation({ source }: { source: string }) {
  const [failure, setFailure] = useState<{ source: string; error: string } | null>(null)
  let document: Document | null = null
  let error: string | null = null
  let processing = false
  let processingLabel = 'PENGUIN processing'
  let classifierGlyph: string | null = null
  let preparation = false
  let gestalt: string | null = null
  try {
    const value: unknown = JSON.parse(source)
    if (!value || typeof value !== 'object' || !('document' in value)) {
      throw new Error('Direct operation document missing')
    }
    document = value.document as Document
    if ('diagnostic' in value && value.diagnostic && typeof value.diagnostic === 'object'
      && 'schema' in value.diagnostic && value.diagnostic.schema === 'catalyst-intent-preparation/1'
    ) {
      preparation = true
      processing = 'pending' in value.diagnostic && value.diagnostic.pending === true
      const diagnostic = value.diagnostic
      if ('classifier_response' in diagnostic && typeof diagnostic.classifier_response === 'string'
        && ['🧠', '🔎', '🤖'].includes(diagnostic.classifier_response.trim())) {
        classifierGlyph = diagnostic.classifier_response.trim()
      }
      if ('phase' in diagnostic) {
        if (diagnostic.phase === 'classification') {processingLabel = 'PENGUIN classifying'}
        if (diagnostic.phase === 'semantic-preparation') {processingLabel = 'PENGUIN preparing GESTALT'}
        if (diagnostic.phase === 'lucid-preparation') {processingLabel = 'PENGUIN formatting LUCID'}
        if (diagnostic.phase === 'execution') {processingLabel = 'Executing request'}
      }
      if ('phase' in diagnostic && diagnostic.phase === 'prepared'
        && 'proposal' in diagnostic && diagnostic.proposal && typeof diagnostic.proposal === 'object'
        && 'classification' in diagnostic.proposal && diagnostic.proposal.classification === 'semantic'
        && 'transformed_input' in diagnostic && typeof diagnostic.transformed_input === 'string'
        && diagnostic.transformed_input.length > 0) {
        gestalt = diagnostic.transformed_input
      }
    }
    if (document?.schema !== 'lucid-ugui-response/1' || !['document', 'lucid'].includes(document.type)) {
      throw new Error('Direct operation document invalid')
    }
  } catch (cause) {
    error = String(cause).slice(0, 512)
  }
  const projectionError = error ?? (failure?.source === source ? failure.error : null)
  const copyPayload = projectionError ? JSON.stringify({ source, projection_error: projectionError }) : source
  return (
    <div className="w-full min-w-0 space-y-2" data-direct-operation="true" data-message-origin={preparation ? 'user-penguin' : 'user-operation'} aria-busy={processing}>
      {preparation && <div className="text-xs font-medium text-muted-foreground">From user / PENGUIN</div>}
      {classifierGlyph && <div className="text-xs text-muted-foreground" aria-label="Selected route">{classifierGlyph}</div>}
      {processing && <div className="flex items-center gap-2" aria-live="polite">
        <Loader role="status" label={processingLabel} />
        <span>{processingLabel}</span>
      </div>}
      <CopyButton appearance="inline" label="Copy operation diagnostics" showLabel text={copyPayload} />
      {error ? <div role="alert" className="text-destructive">{error}</div> : (
        <ProjectionBoundary key={source} onFailure={error => setFailure({ source, error })}>
          {gestalt !== null ? (
            <UguiTextContent text={gestalt} isRunning={false} copyText={copyPayload} allowContinuations={false} />
          ) : document && <McpUguiDocument document={document} copyText={copyPayload} presentationOnly />}
        </ProjectionBoundary>
      )}
    </div>
  )
}