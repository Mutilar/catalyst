import {
  type ComponentProps,
  memo,
  type PointerEvent as ReactPointerEvent,
  useCallback,
  useEffect,
  useRef,
  useState
} from 'react'

import {
  CodeCard,
  CodeCardBody,
  CodeCardHeader,
  CodeCardIcon,
  CodeCardSubtitle,
  CodeCardTitle
} from '@/components/chat/code-card'
import { CompactMarkdown } from '@/components/chat/compact-markdown'
import { ExpandableBlock } from '@/components/chat/expandable-block'
import { SyntaxHighlighter } from '@/components/chat/shiki-highlighter'
import { CopyButton, type CopyButtonProps } from '@/components/ui/copy-button'
import { useI18n } from '@/i18n'
import { invokeUguiAction } from '@/hermes'
import { DELIMITER_SEGMENT, SIGNAL_GREEN, SIGNAL_PENDING, SIGNAL_RED, SIGNAL_WARNING } from '@/lib/ae-glyphs'
import { codiconForLanguage } from '@/lib/markdown-code'
import { resolveUguiMediaReference } from '@/lib/media'
import {
  extractMcpUguiDocument,
  type McpUguiDocument as McpUguiDocumentValue
} from '@/lib/tool-presentation'
import {
  inputResidentUguiApp,
  loadResidentUguiApp,
  mountResidentUguiDocument,
  projectMcpGestaltResult,
  resetResidentUguiApp,
  type ResidentUguiAppDocument
} from '@/lib/ugui-engine'
import { cn } from '@/lib/utils'
import { ingestLucidHostAppearance } from '@/themes/backend-sync'

const SIGNAL_CLASS: Record<string, string> = {
  [SIGNAL_GREEN]: 'text-emerald-600 dark:text-emerald-400',
  [SIGNAL_PENDING]: 'text-sky-600 dark:text-sky-400',
  [SIGNAL_WARNING]: 'text-amber-600 dark:text-amber-400',
  [SIGNAL_RED]: 'text-rose-600 dark:text-rose-400'
}

const LUCID_VERBS = new Set(['show', 'get', 'set', 'morph', 'dispatch', 'steer', 'cancel'])
const MUTATING_LUCID_VERBS = new Set(['set', 'dispatch', 'steer'])
const MUTATING_MORPH_OPERATIONS = new Set(['start', 'customize', 'write', 'advance'])
const READ_MORPH_OPERATIONS = new Set(['inspect', 'shard', 'vocabulary', 'project'])
const HASH_RE = /^sha256:[0-9a-f]{64}$/

interface ProjectedAction {
  executable: boolean
  conversationText?: string
  id: string
  input: { id: string; label: string; maxLength: number } | null
  label: string
  reason: string
  requiresConfirmation: boolean
}

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

function text(value: unknown): string {
  if (typeof value === 'string') {
    return value
  }

  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value)
  }

  if (value == null) {
    return ''
  }

  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

function uguiDocumentIdentity(document: McpUguiDocumentValue): string {
  const provenanceHash = text(record(document.provenance)?.parentHash)

  return provenanceHash || JSON.stringify([document.schema, document.id, document.state, document.header])
}

export function projectUguiAction(
  document: McpUguiDocumentValue,
  value: unknown,
  index: number
): ProjectedAction {
  const action = record(value) ?? {}
  const id = text(action.id)
  const label = text(action.label ?? action.title ?? action.action ?? action.id ?? `Action ${index + 1}`)
  const handler = text(action.action)
  const intent = record(action.intent)
  const verb = text(intent?.verb)
  const argumentsValue = record(intent?.arguments)
  const provenanceHash = text(record(document.provenance)?.parentHash)
  const receipts = record(document.receipt)?.action_provenance

  const receipt = Array.isArray(receipts)
    ? receipts.map(record).find(item => item?.id === id && item?.provenance_hash === provenanceHash)
    : null

  const verbHelp = handler === 'lucid.help.verb'
  const nounHelp = handler === 'lucid.help.noun'
  const helpHandler = verbHelp || nounHelp
  const morphOperation = text(argumentsValue?.operation)

  const morphOperationValid =
    verb !== 'morph' ||
    helpHandler ||
    READ_MORPH_OPERATIONS.has(morphOperation) ||
    MUTATING_MORPH_OPERATIONS.has(morphOperation)

  const handlerMatches = verbHelp
    ? LUCID_VERBS.has(verb) && Object.keys(argumentsValue ?? {}).length === 0 && action.value === verb
    : nounHelp
      ? LUCID_VERBS.has(verb) && Object.keys(argumentsValue ?? {}).length === 1 &&
        typeof argumentsValue?.help === 'string' && argumentsValue.help === action.value &&
        /^[A-Za-z0-9][A-Za-z0-9_./:-]{0,127}$/.test(argumentsValue.help)
      : LUCID_VERBS.has(verb) && handler.startsWith(`lucid.${verb}.`)

  const choiceTargetValid =
    handler !== 'lucid.morph.choice' ||
    (typeof action.value === 'string' && action.value === argumentsValue?.codebook)

  const cancelTargetValid =
    handler !== 'lucid.cancel.dispatch' ||
    (action.value === argumentsValue?.id &&
      argumentsValue?.mode === 'graceful' &&
      Object.keys(argumentsValue).length === 2)

  const steerTargetValid =
    handler !== 'lucid.steer.compose' ||
    (action.value === argumentsValue?.dispatch_id &&
      argumentsValue?.intent_delta === '' &&
      Object.keys(argumentsValue).length === 2)

  const semanticTargetValid =
    choiceTargetValid &&
    cancelTargetValid &&
    steerTargetValid &&
    (handler !== 'lucid.get.readback' || action.value === argumentsValue?.path) &&
    (!handler.endsWith('.continue') || action.value === provenanceHash)

  const producerDisabled = action.disabled === true
  const actionInputs = Array.isArray(action.inputs) ? action.inputs.map(record) : []
  const steerInput = actionInputs.length === 1 ? actionInputs[0] : null

  const typedInputValid =
    !Array.isArray(action.inputs) ||
    (handler === 'lucid.steer.compose' &&
      steerInput?.id === 'intent_delta' &&
      steerInput.type === 'text' &&
      steerInput.required === true &&
      steerInput.maxLength === 4000)

  const unavailable = receipt?.state !== 'AVAILABLE'

  const complete = Boolean(
    id &&
      label &&
      intent &&
      argumentsValue &&
      handlerMatches &&
      morphOperationValid &&
      semanticTargetValid &&
      typedInputValid
  )

  const requiresExactConfirmation =
    !helpHandler &&
    (MUTATING_LUCID_VERBS.has(verb) ||
      (verb === 'morph' && MUTATING_MORPH_OPERATIONS.has(morphOperation)))

  const confirmationPolicyValid = !requiresExactConfirmation || action.requiresConfirmation === 'exact'

  const executable =
    complete &&
    confirmationPolicyValid &&
    HASH_RE.test(provenanceHash) &&
    !producerDisabled &&
    !unavailable

  const reason = producerDisabled
    ? text(action.disabledReason) || 'The producer disabled this action.'
    : unavailable
      ? text(receipt?.reason) || 'This action is unavailable for the current document.'
      : !typedInputValid
        ? 'The action typed-input contract is invalid.'
        : !confirmationPolicyValid
          ? 'Mutating LUCID actions require authored exact confirmation.'
        : !morphOperationValid
          ? 'MORPH actions require one closed operation.'
        : !semanticTargetValid
          ? 'Action target differs from its exact request.'
        : !complete
          ? 'The producer has not supplied a complete typed LUCID intent for this action.'
          : !HASH_RE.test(provenanceHash)
            ? 'The document action provenance is invalid.'
            : ''

  return {
    executable,
    id,
    input: steerInput
      ? { id: 'intent_delta', label: text(steerInput.label) || 'Correction', maxLength: 4000 }
      : null,
    label,
    reason,
    requiresConfirmation: action.requiresConfirmation === 'exact'
  }
}

function UgUiKeyValue({ rows }: { rows: unknown[] }) {
  return (
    <dl className="grid gap-x-3 gap-y-1 sm:grid-cols-[minmax(5rem,auto)_minmax(0,1fr)]">
      {rows.slice(0, 64).map((value, index) => {
        const row = record(value) ?? {}
        const label = text(row.label ?? row.key ?? row.name ?? `Field ${index + 1}`)
        const body = text(row.value ?? row.body ?? row.text ?? '')

        return (
          <div className="contents" key={text(row.id) || `${label}-${index}`}>
            <dt className="text-[0.65rem] font-medium uppercase tracking-[0.06em] text-(--ui-text-tertiary)">
              {label}
            </dt>
            <dd className="min-w-0 whitespace-pre-wrap wrap-anywhere text-(--ui-text-secondary)">{body}</dd>
          </div>
        )
      })}
    </dl>
  )
}

function UgUiDataTable({ columns, rows }: { columns: unknown[]; rows: unknown[] }) {
  const labels = columns.map(text)

  return (
    <div className="max-h-72 overflow-auto rounded-[0.2rem] border border-(--ui-stroke-tertiary)">
      <table className="w-full border-collapse text-left text-[0.68rem]">
        <thead className="sticky top-0 bg-(--ui-bg-quinary) text-(--ui-text-tertiary)">
          <tr>
            {labels.map((label, index) => (
              <th className="px-2 py-1 font-medium" key={`${label}-${index}`}>
                {label || `Column ${index + 1}`}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((value, rowIndex) => {
            const cells = Array.isArray(value) ? value : Object.values(record(value) ?? {})

            return (
              <tr className="border-t border-(--ui-stroke-tertiary) align-top" key={rowIndex}>
                {labels.map((_, cellIndex) => (
                  <td
                    className="max-w-80 whitespace-pre-wrap wrap-anywhere px-2 py-1 text-(--ui-text-secondary)"
                    key={cellIndex}
                  >
                    {text(cells[cellIndex])}
                  </td>
                ))}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function UguiCodePre(props: ComponentProps<'pre'>) {
  return <pre {...props} />
}

function UguiCode(props: ComponentProps<'code'>) {
  return <code {...props} />
}

function UguiMarkdownCode({ code, language, title }: { code: string; language: string; title: string }) {
  const source = code.replace(/^\n+/, '').trimEnd()

  if (!source.trim()) {
    return null
  }

  return (
    <CodeCard data-ugui-renderer="streamdown">
      <CodeCardHeader>
        <CodeCardTitle>
          <CodeCardIcon name={codiconForLanguage(language)} />
          {title}
            <CodeCardSubtitle>{DELIMITER_SEGMENT}{language}</CodeCardSubtitle>
        </CodeCardTitle>
        <CopyButton
          appearance="inline"
          className="-my-1 -mr-1 h-5 px-1 opacity-55 hover:opacity-100"
          iconClassName="size-2.5"
          label="Copy Markdown source"
          showLabel={false}
          text={source}
        />
      </CodeCardHeader>
      <CodeCardBody className="font-sans text-xs">
        <ExpandableBlock>
          <CompactMarkdown className="px-2 py-1.5" text={source} />
        </ExpandableBlock>
      </CodeCardBody>
    </CodeCard>
  )
}

export function residentUguiActionId(target: EventTarget | null): string {
  if (!(target instanceof Element)) {return ''}
  const action = target.closest('[data-ugui-action]')

  return action?.getAttribute('data-ugui-action') ?? ''
}

function UgUiResidentAppReference({ value }: { value: Record<string, unknown> }) {
  const appId = text(value.appId)
  const source = text(value.source)
  const root = useRef<HTMLDivElement | null>(null)
  const sending = useRef(false)
  const [document, setDocument] = useState<ResidentUguiAppDocument | null>(null)
  const [error, setError] = useState('')

  const send = useCallback(async (message: Record<string, unknown>) => {
    if (sending.current) {return}
    sending.current = true

    try {
      const next = await inputResidentUguiApp(message)
      setDocument(next)
      setError('')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'UGUI app input failed')
    } finally {
      sending.current = false
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    setDocument(null)
    setError('')
    void loadResidentUguiApp(appId, source, 20_260_702)
      .then(next => {
        if (!cancelled) {setDocument(next)}
      })
      .catch(cause => {
        if (!cancelled) {
          setError(cause instanceof Error ? cause.message : 'UGUI app load failed')
        }
      })

    return () => {
      cancelled = true
      void resetResidentUguiApp()
    }
  }, [appId, source])

  useEffect(() => {
    if (!document || !root.current) {return}
    void mountResidentUguiDocument(root.current, document).catch(cause => {
      setError(cause instanceof Error ? cause.message : 'UGUI browser paint failed')
    })
  }, [document])

  useEffect(() => {
    if (!document) {return}
    const timer = window.setInterval(() => void send({ kind: 'tick', dt: 100 }), 100)

    return () => window.clearInterval(timer)
  }, [document, send])

  const key = (value: string) => {
    const normalized: Record<string, string> = {
      ArrowUp: 'up',
      ArrowDown: 'down',
      ArrowLeft: 'left',
      ArrowRight: 'right',
      Escape: 'esc'
    }

    return normalized[value] ?? (/^[a-z]$/i.test(value) ? value.toLowerCase() : '')
  }

  const pointer = (event: ReactPointerEvent<HTMLDivElement>, phase: 'down' | 'move' | 'up') => {
    if (!(event.target instanceof HTMLCanvasElement)) {return}
    const bounds = event.target.getBoundingClientRect()

    if (!bounds.width || !bounds.height) {return}
    const x = Math.round(((event.clientX - bounds.left) * event.target.width) / bounds.width)
    const y = Math.round(((event.clientY - bounds.top) * event.target.height) / bounds.height)
    void send({ kind: 'pointer', phase, x, y })
  }

  return (
    <section className="rounded-[0.25rem] bg-(--ui-bg-quinary) p-2" data-ugui-app-reference={appId}>
      <div
        className="max-h-[32rem] overflow-auto outline-none [&_button]:m-1 [&_button]:rounded [&_button]:border [&_button]:border-(--ui-stroke-tertiary) [&_button]:px-2 [&_button]:py-1 [&_canvas]:max-w-full [&_canvas]:image-rendering-pixelated"
        onClick={event => {
          const id = residentUguiActionId(event.target)

          if (id) {void send({ kind: 'tap', id })}
        }}
        onInput={event => {
          const target = event.target

          if (!(target instanceof HTMLInputElement)) {return}

          if (!residentUguiActionId(target)) {return}
          void send({ kind: 'text', value: target.value })
        }}
        onKeyDown={event => {
          const value = key(event.key)

          if (!value) {return}
          event.preventDefault()
          void send({ kind: 'key', key: value })
        }}
        onPointerDown={event => pointer(event, 'down')}
        onPointerMove={event => {
          if (event.buttons) {pointer(event, 'move')}
        }}
        onPointerUp={event => pointer(event, 'up')}
        ref={root}
        role="application"
        tabIndex={0}
      />
      {error && <p className="mt-1 text-[0.68rem] text-rose-600 dark:text-rose-400">{error}</p>}
    </section>
  )
}

function UgUiImage({ value }: { value: Record<string, unknown> }) {
  const src = text(value.src)
  const alt = text(value.alt)
  const [resolvedSrc, setResolvedSrc] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    setResolvedSrc('')
    setError('')
    void resolveUguiMediaReference(src)
      .then(result => {
        if (!cancelled) {setResolvedSrc(result)}
      })
      .catch(cause => {
        if (!cancelled) {
          setError(cause instanceof Error ? cause.message : 'UGUI image reference failed')
        }
      })

    return () => {
      cancelled = true
    }
  }, [src])

  if (!src || !alt) {
    return null
  }

  return (
    <figure className="space-y-1 rounded-[0.25rem] bg-(--ui-bg-quinary) p-2" data-ugui-primitive="image">
      {resolvedSrc ? (
        <img
          alt={alt}
          className="max-h-[min(32rem,60vh)] max-w-full rounded object-contain"
          height={Number(value.pixelHeight) || undefined}
          src={resolvedSrc}
          width={Number(value.pixelWidth) || undefined}
        />
      ) : (
        <p className="text-[0.68rem] text-(--ui-text-tertiary)">
          {error || 'Resolving image reference…'}
        </p>
      )}
      <figcaption className="text-[0.65rem] text-(--ui-text-tertiary)">{alt}</figcaption>
    </figure>
  )
}

function UguiSectionImpl({ value, presentationOnly = false }: { value: unknown; presentationOnly?: boolean }) {
  const section = record(value)

  if (!section) {
    return null
  }

  const type = text(section.type)
  const heading = text(section.heading ?? section.title)
  const body = text(section.body ?? section.text)
  const signal = text(section.signal)

  if (type === 'app_reference') {
    if (presentationOnly) {return <CompactMarkdown text={text(section.source)} />}
    return <UgUiResidentAppReference value={section} />
  }

  if (type === 'image') {
    return <UgUiImage value={section} />
  }

  if (type === 'status') {
    return (
      <section className="flex items-start gap-2 rounded-[0.25rem] bg-(--ui-bg-quinary) px-2 py-1.5">
        {signal && <span className={cn('shrink-0 font-medium', SIGNAL_CLASS[signal])}>{signal}</span>}
        <div className="min-w-0">
          {heading && <p className="font-medium text-(--ui-text-primary)">{heading}</p>}
          {body && <CompactMarkdown className="wrap-anywhere text-(--ui-text-secondary)" text={body} />}
        </div>
      </section>
    )
  }

  if (type === 'key_value' && Array.isArray(section.rows)) {
    return (
      <section className="rounded-[0.25rem] bg-(--ui-bg-quinary) px-2 py-1.5">
        {heading && <p className="mb-1 font-medium text-(--ui-text-primary)">{heading}</p>}
        <UgUiKeyValue rows={section.rows} />
      </section>
    )
  }

  if (type === 'data_table' && Array.isArray(section.columns) && Array.isArray(section.rows)) {
    return (
      <section className="rounded-[0.25rem] bg-(--ui-bg-quinary) px-2 py-1.5">
        {heading && <p className="mb-1 font-medium text-(--ui-text-primary)">{heading}</p>}
        <UgUiDataTable columns={section.columns} rows={section.rows} />
      </section>
    )
  }

  if (type === 'code') {
    const value = text(section.value)
    const language = text(section.language) || 'text'
    const label = heading || text(section.label) || 'Code'
    const rendersMarkdown = ['markdown', 'md'].includes(language.toLowerCase())

    return (
      <section data-ugui-primitive="code">
        {rendersMarkdown ? (
          <UguiMarkdownCode code={value} language={language} title={label} />
        ) : (
          <div data-ugui-renderer="shiki">
            <SyntaxHighlighter
              code={value}
              components={{ Code: UguiCode, Pre: UguiCodePre }}
              language={language}
              title={label}
            />
          </div>
        )}
      </section>
    )
  }

  if (type === 'nested' && Array.isArray(section.sections)) {
    const title = heading || text(section.label) || 'Details'

    return (
      <details
        className="rounded-[0.25rem] bg-(--ui-bg-quinary) px-2 py-1.5"
        data-ugui-primitive="nested"
        open={section.expanded !== false}
      >
        <summary className="cursor-pointer font-medium text-(--ui-text-primary)">{title}</summary>
        <div className="mt-2 space-y-2">
          {section.sections.slice(0, 64).map((child, index) => (
            <UgUiSection key={text(record(child)?.id) || index} presentationOnly={presentationOnly} value={child} />
          ))}
        </div>
      </details>
    )
  }

  if (type === 'alert_list' && Array.isArray(section.alerts)) {
    if (section.alerts.length === 0) {
      return null
    }

    return (
      <section className="space-y-1 rounded-[0.25rem] bg-(--ui-bg-quinary) px-2 py-1.5">
        {heading && <p className="font-medium text-(--ui-text-primary)">{heading}</p>}
        {section.alerts.slice(0, 32).map((alert, index) => {
          const row = record(alert) ?? {}
          const alertSignal = text(row.signal)

          return (
            <div className="flex gap-2" key={text(row.id) || index}>
              {alertSignal && <span className={SIGNAL_CLASS[alertSignal]}>{alertSignal}</span>}
              <span className="whitespace-pre-wrap wrap-anywhere text-(--ui-text-secondary)">
                {text(row.body ?? row.detail ?? row.message ?? row.title ?? alert)}
              </span>
            </div>
          )
        })}
      </section>
    )
  }

  if (body) {
    return (
      <section className="rounded-[0.25rem] bg-(--ui-bg-quinary) px-2 py-1.5">
        {heading && <p className="mb-1 font-medium text-(--ui-text-primary)">{heading}</p>}
        <CompactMarkdown className="wrap-anywhere text-(--ui-text-secondary)" text={body} />
      </section>
    )
  }

  const data = Object.fromEntries(
    Object.entries(section).filter(([key]) => !['id', 'type', 'width', 'style', 'heading', 'title'].includes(key))
  )

  return Object.keys(data).length ? (
    <section className="rounded-[0.25rem] bg-(--ui-bg-quinary) px-2 py-1.5">
      {heading && <p className="mb-1 font-medium text-(--ui-text-primary)">{heading}</p>}
      <pre className="max-h-40 overflow-auto whitespace-pre-wrap wrap-anywhere font-mono text-[0.68rem] text-(--ui-text-secondary)">
        {JSON.stringify(data, null, 2)}
      </pre>
    </section>
  ) : null
}

const UgUiSection = memo(UguiSectionImpl)

const UGUI_RESPONSIVE_SPAN: Record<number, string> = {
  1: '@lg:col-span-1',
  2: '@lg:col-span-2',
  3: '@lg:col-span-3',
  4: '@lg:col-span-4',
  5: '@lg:col-span-5',
  6: '@lg:col-span-6',
  7: '@lg:col-span-7',
  8: '@lg:col-span-8',
  9: '@lg:col-span-9',
  10: '@lg:col-span-10',
  11: '@lg:col-span-11',
  12: '@lg:col-span-12'
}

function uguiResponsiveSpan(value: unknown): string {
  const width = Number(record(value)?.width ?? 12)

  const span = Math.max(1, Math.min(12, Number.isFinite(width) ? Math.round(width) : 12))

  return UGUI_RESPONSIVE_SPAN[span] ?? '@lg:col-span-12'
}

export function McpUguiDocument({ document, presentationOnly = false, onContinuation, copyText }: {
  document: McpUguiDocumentValue
  presentationOnly?: boolean
  onContinuation?: (text: string) => void
  copyText?: CopyButtonProps['text']
}) {
  const { t } = useI18n()
  const [actionDocument, setRendered] = useState(document)
  const rendered = presentationOnly ? document : actionDocument
  const [pendingAction, setPendingAction] = useState('')
  const [confirmationAction, setConfirmationAction] = useState('')
  const [actionError, setActionError] = useState('')
  const [actionStatus, setActionStatus] = useState('')
  const [actionInputs, setActionInputs] = useState<Record<string, string>>({})
  const actionInFlight = useRef('')
  const appliedHostEffect = useRef('')
  const receivedDocumentIdentity = useRef(uguiDocumentIdentity(document))

  useEffect(() => {
    if (presentationOnly) {return}
    const identity = uguiDocumentIdentity(document)

    if (receivedDocumentIdentity.current === identity) {
      return
    }

    receivedDocumentIdentity.current = identity
    setRendered(document)
    setPendingAction('')
    setConfirmationAction('')
    setActionError('')
    setActionStatus('')
    setActionInputs({})
    actionInFlight.current = ''
  }, [document, presentationOnly])

  useEffect(() => {
    if (presentationOnly) {return}
    const hostEffect = rendered.hostEffect
    const identity = hostEffect ? JSON.stringify(hostEffect) : ''

    if (!identity || appliedHostEffect.current === identity) {
      return
    }

    if (ingestLucidHostAppearance(hostEffect)) {
      appliedHostEffect.current = identity
    }
  }, [rendered.hostEffect, presentationOnly])

  const activateAction = async (projected: ProjectedAction) => {
    const { executable, id: actionId, label } = projected

    if (presentationOnly) {
      if (executable && projected.conversationText) {onContinuation?.(projected.conversationText)}
      return
    }
    if (!executable) {return}

    const inputValue = projected.input ? (actionInputs[actionId] ?? '').trim() : ''

    if (projected.input && !inputValue) {
      setActionError(`${projected.input.label} is required.`)

      return
    }

    if (projected.requiresConfirmation && confirmationAction !== actionId) {
      setConfirmationAction(actionId)
      setActionError('')
      setActionStatus(`Confirmation required for ${label}.`)

      return
    }

    if (actionInFlight.current) {
      return
    }

    actionInFlight.current = actionId
    setPendingAction(actionId)
    setActionError('')
    setActionStatus(`Running ${label}…`)

    try {
      const response = await invokeUguiAction(
        rendered as unknown as Record<string, unknown>,
        actionId,
        confirmationAction === actionId,
        projected.input ? { [projected.input.id]: inputValue } : {}
      )

      const next =
        extractMcpUguiDocument(response.result) ?? (await projectMcpGestaltResult(response.result))

      if (!next) {
        throw new Error('LUCID action completed without a replacement UGUI document')
      }

      setRendered(next)
      setActionStatus('')
      setConfirmationAction('')
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'UGUI action failed')
    } finally {
      actionInFlight.current = ''
      setPendingAction('')
    }
  }

  const heading = rendered.header
    .map(value => text(record(value)?.body ?? record(value)?.text))
    .filter(Boolean)
    .join(DELIMITER_SEGMENT)

  const projectedActions = (rendered.actions ?? [])
    .filter(action => !presentationOnly || record(action)?.action === 'conversation.submit')
    .slice(0, 32)
    .map((value, index): ProjectedAction => {
      if (!presentationOnly) {return projectUguiAction(rendered, value, index)}
      const action = record(value) ?? {}
      const prompt = typeof action.value === 'string' ? action.value : ''
      const label = text(action.label)
      return {
        id: text(action.id), label, conversationText: prompt,
        executable: action.disabled !== true && Boolean(prompt && label && onContinuation),
        input: null, reason: '', requiresConfirmation: false
      }
    })

  const helpAction = projectedActions.find(action => action.id === 'lucid.response.help')
  const primaryActions = projectedActions.filter(action => action.id !== 'lucid.response.help')

  return (
    <article
      className="@container min-w-0 w-full max-w-full space-y-1.5 rounded-[0.3125rem] border border-(--ui-stroke-tertiary) bg-(--ui-bg-elevated) p-2 text-xs"
      data-mcp-ugui={rendered.schema}
      data-ugui-authority={presentationOnly ? 'presentation-only' : 'tool'}
    >
      <header className="flex min-w-0 items-start justify-between gap-2">
        <h4 className="min-w-0 flex-1 wrap-anywhere font-semibold text-(--ui-text-primary)">{heading}</h4>
        <span className="flex shrink-0 items-center gap-1">
          <CopyButton appearance="inline" label={t.assistant.tool.copyOutput} showLabel text={copyText ?? JSON.stringify(rendered, null, 2)} />
          {rendered.state && (
            <span className="rounded bg-(--ui-bg-quinary) px-1.5 py-0.5 text-[0.62rem] uppercase tracking-[0.06em] text-(--ui-text-tertiary)">
              {rendered.state}
            </span>
          )}
          {helpAction && (
            <button
              aria-label={helpAction.label}
              className="rounded border border-(--ui-stroke-tertiary) px-1.5 py-0.5 text-[0.65rem] text-(--ui-text-tertiary) enabled:hover:bg-(--ui-bg-tertiary) disabled:opacity-50"
              disabled={!helpAction.executable || Boolean(pendingAction)}
              onClick={() => void activateAction(helpAction)}
              title={helpAction.executable ? undefined : helpAction.reason}
              type="button"
            >
              ?
            </button>
          )}
        </span>
      </header>
      <div className="grid grid-cols-12 gap-[var(--ugui-section-gap)]" data-ugui-layout="responsive-grid">
        {rendered.sections.map((section, index) => (
          <div
            className={cn('col-span-12 min-w-0', uguiResponsiveSpan(section))}
            data-ugui-width={String(record(section)?.width ?? 12)}
            key={text(record(section)?.id) || index}
          >
            <UgUiSection presentationOnly={presentationOnly} value={section} />
          </div>
        ))}
      </div>
      {actionStatus && (
        <p aria-live="polite" className="text-[0.68rem] text-(--ui-text-tertiary)">
          {actionStatus}
        </p>
      )}
      {actionError && (
        <p aria-live="assertive" className="text-[0.68rem] text-rose-600 dark:text-rose-400">
          {actionError}
        </p>
      )}
      {primaryActions.length > 0 && (
        <footer className="flex flex-wrap items-center gap-1 pt-0.5">
          {primaryActions.map(projected => {
            const pending = pendingAction === projected.id

            return (
              <span className="flex min-w-0 max-w-full items-center gap-1" key={projected.id}>
                {projected.input && (
                  <input
                    aria-label={projected.input.label}
                    className="min-w-32 rounded border border-(--ui-stroke-tertiary) bg-(--ui-bg-primary) px-1.5 py-0.5 text-[0.65rem] text-(--ui-text-primary)"
                    maxLength={projected.input.maxLength}
                    onChange={event =>
                      setActionInputs(current => ({ ...current, [projected.id]: event.target.value }))
                    }
                    placeholder={projected.input.label}
                    type="text"
                    value={actionInputs[projected.id] ?? ''}
                  />
                )}
                <button
                  aria-busy={pending}
                  aria-label={projected.label}
                  className="max-w-full whitespace-normal wrap-anywhere rounded border border-(--ui-stroke-tertiary) bg-(--ui-bg-quinary) px-1.5 py-0.5 text-left text-[0.65rem] text-(--ui-text-secondary) enabled:hover:bg-(--ui-bg-tertiary) disabled:cursor-not-allowed disabled:opacity-50"
                  disabled={!projected.executable || Boolean(pendingAction)}
                  onClick={() => void activateAction(projected)}
                  title={projected.executable ? undefined : projected.reason}
                  type="button"
                >
                  {pending ? 'Working…' : projected.label}
                </button>
              </span>
            )
          })}
          {confirmationAction && (
            <span className="flex items-center gap-1 text-[0.65rem] text-amber-700 dark:text-amber-300">
              Confirm exact action?
              <button
                className="rounded border border-amber-500/50 px-1.5 py-0.5"
                onClick={() => {
                  const action = projectedActions.find(value => value.id === confirmationAction)

                  if (action) {void activateAction(action)}
                }}
                type="button"
              >
                Confirm {projectedActions.find(value => value.id === confirmationAction)?.label ?? 'action'}
              </button>
              <button
                className="rounded border border-(--ui-stroke-tertiary) px-1.5 py-0.5"
                onClick={() => setConfirmationAction('')}
                type="button"
              >
                Go back
              </button>
            </span>
          )}
        </footer>
      )}
    </article>
  )
}
