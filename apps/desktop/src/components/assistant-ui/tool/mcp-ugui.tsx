import { CompactMarkdown } from '@/components/chat/compact-markdown'
import type { McpUguiDocument as McpUguiDocumentValue } from '@/lib/tool-presentation'
import { cn } from '@/lib/utils'

const SIGNAL_CLASS: Record<string, string> = {
  '🟢': 'text-emerald-600 dark:text-emerald-400',
  '⏳': 'text-sky-600 dark:text-sky-400',
  '⚠️': 'text-amber-600 dark:text-amber-400',
  '🔴': 'text-rose-600 dark:text-rose-400'
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

function UgUiSection({ value }: { value: unknown }) {
  const section = record(value)

  if (!section) {
    return null
  }

  const type = text(section.type)
  const heading = text(section.heading ?? section.title)
  const body = text(section.body ?? section.text)
  const signal = text(section.signal)

  if (type === 'status') {
    return (
      <section className="flex items-start gap-2 rounded-[0.25rem] bg-(--ui-bg-quinary) px-2 py-1.5">
        {signal && <span className={cn('shrink-0 font-medium', SIGNAL_CLASS[signal])}>{signal}</span>}
        <div className="min-w-0">
          {heading && <p className="font-medium text-(--ui-text-primary)">{heading}</p>}
          {body && <p className="whitespace-pre-wrap wrap-anywhere text-(--ui-text-secondary)">{body}</p>}
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

    return (
      <section className="rounded-[0.25rem] bg-(--ui-bg-quinary) px-2 py-1.5">
        {(heading || text(section.label)) && (
          <p className="mb-1 font-medium text-(--ui-text-primary)">{heading || text(section.label)}</p>
        )}
        <pre className="max-h-72 overflow-auto whitespace-pre-wrap wrap-anywhere font-mono text-[0.68rem] text-(--ui-text-secondary)">
          {value}
        </pre>
      </section>
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

export function McpUguiDocument({ document }: { document: McpUguiDocumentValue }) {
  const heading = document.header
    .map(value => text(record(value)?.body ?? record(value)?.text))
    .filter(Boolean)
    .join(' · ')

  return (
    <article
      className="space-y-1.5 rounded-[0.3125rem] border border-(--ui-stroke-tertiary) bg-(--ui-bg-elevated) p-2 text-xs"
      data-mcp-ugui={document.schema}
    >
      <header className="flex min-w-0 items-center justify-between gap-2">
        <h4 className="min-w-0 truncate font-semibold text-(--ui-text-primary)">{heading || document.id}</h4>
        {document.state && (
          <span className="shrink-0 rounded bg-(--ui-bg-quinary) px-1.5 py-0.5 text-[0.62rem] uppercase tracking-[0.06em] text-(--ui-text-tertiary)">
            {document.state}
          </span>
        )}
      </header>
      {document.sections.map((section, index) => (
        <UgUiSection key={text(record(section)?.id) || index} value={section} />
      ))}
      {document.actions && document.actions.length > 0 && (
        <footer className="flex flex-wrap gap-1 pt-0.5">
          {document.actions.slice(0, 32).map((action, index) => {
            const row = record(action) ?? {}
            const label = text(row.label ?? row.title ?? row.action ?? row.id ?? `Action ${index + 1}`)

            return (
              <span
                className="rounded border border-(--ui-stroke-tertiary) bg-(--ui-bg-quinary) px-1.5 py-0.5 text-[0.65rem] text-(--ui-text-secondary)"
                key={text(row.id) || index}
              >
                {label}
              </span>
            )
          })}
        </footer>
      )}
    </article>
  )
}
