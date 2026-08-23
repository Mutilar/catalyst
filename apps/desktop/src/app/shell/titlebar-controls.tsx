import { useStore } from '@nanostores/react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { type ComponentProps, type MouseEvent, type ReactNode, useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

import { McpUguiDocument } from '@/components/assistant-ui/tool/mcp-ugui'
import { toggleLayoutEditMode } from '@/components/pane-shell/edit-mode'
import { resetLayoutTree } from '@/components/pane-shell/tree/store'
import { Button } from '@/components/ui/button'
import { Codicon } from '@/components/ui/codicon'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  preventCloseButtonAutoFocus
} from '@/components/ui/dialog'
import { Tip, TipKeybindLabel } from '@/components/ui/tooltip'
import { listMcpServers } from '@/hermes'
import { useI18n } from '@/i18n'
import { triggerHaptic } from '@/lib/haptics'
import { deriveLucidMcpStatus, lucidMcpGestalt } from '@/lib/lucid-mcp-status'
import type { McpUguiDocument as McpUguiDocumentValue } from '@/lib/tool-presentation'
import { projectLucidGestalt } from '@/lib/ugui-engine'
import { cn } from '@/lib/utils'
import { $hapticsMuted, toggleHapticsMuted } from '@/store/haptics'
import { $activeGatewayProfile, normalizeProfileKey } from '@/store/profile'
import {
  $fileBrowserOpen,
  $sidebarOpen,
  toggleFileBrowserOpen,
  togglePanesFlipped,
  toggleSidebarOpen
} from '@/store/layout'

import { appViewForPath, isOverlayView, SETTINGS_ROUTE, SKILLS_ROUTE } from '../routes'

import { titlebarButtonClass } from './titlebar'

export interface TitlebarTool {
  id: string
  label: string
  active?: boolean
  className?: string
  disabled?: boolean
  hidden?: boolean
  href?: string
  icon: ReactNode
  onSelect?: (event?: MouseEvent) => void
  /** Keybind action id — when set, the tooltip shows the label + keybind hint. */
  actionId?: string
  title?: ReactNode
  to?: string
}

export type TitlebarToolSide = 'left' | 'right'
export type SetTitlebarToolGroup = (id: string, tools: readonly TitlebarTool[], side?: TitlebarToolSide) => void

interface TitlebarControlsProps extends ComponentProps<'div'> {
  leftTools?: readonly TitlebarTool[]
  tools?: readonly TitlebarTool[]
  onOpenSettings: () => void
}

interface CatalystRestartIntent {
  schema: 'run-catalyst-restart-intent/1'
  child_id: 'catalyst'
  generation_hash: string
  intent_id: string
  observed_epoch_ms: number
  owner: 'RUN'
  reason: 'source-build-prepared'
  state: 'deferred' | 'pending'
}

interface RestartConsentBridge {
  get: () => Promise<CatalystRestartIntent | null>
  decide: (request: {
    action: 'accept' | 'defer'
    generation_hash: string
    intent_id: string
  }) => Promise<{ accepted: true; action: 'accept' | 'defer'; intent_id: string }>
}

/**
 * The layout button's glyph. Morphs into its composite reset form — the
 * layout icon wearing a small counter-clockwise arrow badge ("layout, back
 * to how it was") — ONLY while the pointer is on the button AND ⌘/Ctrl is
 * held: hover gates via CSS (`group/tool` on the button), the modifier via
 * the window listener. Pressing the modifier elsewhere changes nothing.
 */
function LayoutGlyph({ modHeld }: { modHeld: boolean }) {
  return (
    <>
      <span className={cn('inline-flex', modHeld && 'group-hover/tool:hidden')}>
        <Codicon name="layout" />
      </span>
      <span className={cn('relative hidden', modHeld && 'group-hover/tool:inline-flex')}>
        <Codicon name="layout" />
        <span className="absolute -bottom-1 -right-1.5 grid place-items-center rounded-full bg-(--ui-bg-chrome) p-px">
          <Codicon className="-scale-x-100" name="refresh" size="0.5625rem" />
        </span>
      </span>
    </>
  )
}

/** Live ⌘/Ctrl tracking — mod-click affordances telegraph themselves (the
 *  layout button morphs into its reset form while the modifier is down). */
function useModifierHeld(): boolean {
  const [held, setHeld] = useState(false)

  useEffect(() => {
    const sync = (event: KeyboardEvent) => setHeld(event.metaKey || event.ctrlKey)
    const clear = () => setHeld(false)

    window.addEventListener('keydown', sync)
    window.addEventListener('keyup', sync)
    window.addEventListener('blur', clear)

    return () => {
      window.removeEventListener('keydown', sync)
      window.removeEventListener('keyup', sync)
      window.removeEventListener('blur', clear)
    }
  }, [])

  return held
}

export function TitlebarControls({ leftTools = [], tools = [], onOpenSettings }: TitlebarControlsProps) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const location = useLocation()
  const modHeld = useModifierHeld()
  const hapticsMuted = useStore($hapticsMuted)
  const activeProfile = useStore($activeGatewayProfile)
  const fileBrowserOpen = useStore($fileBrowserOpen)
  const sidebarOpen = useStore($sidebarOpen)
  const lucidRuntime = useQuery({
    queryKey: ['mcp-runtime', normalizeProfileKey(activeProfile)],
    queryFn: listMcpServers,
    refetchInterval: 3_000,
    staleTime: 1_000
  })
  const lucidStatus = deriveLucidMcpStatus(lucidRuntime.data?.servers, {
    error: lucidRuntime.error,
    loading: lucidRuntime.isLoading
  })
  const lucidGestalt = lucidMcpGestalt(lucidStatus)
  const [lucidModalOpen, setLucidModalOpen] = useState(false)
  const [lucidDocument, setLucidDocument] = useState<McpUguiDocumentValue | null>(null)
  const [lucidProjectionFailed, setLucidProjectionFailed] = useState(false)
  const [restartModalOpen, setRestartModalOpen] = useState(false)
  const [restartDecisionPending, setRestartDecisionPending] = useState(false)
  const [restartDecisionError, setRestartDecisionError] = useState<string | null>(null)
  const restartConsent = (
    window.hermesDesktop as typeof window.hermesDesktop & {
      restartConsent?: RestartConsentBridge
    }
  ).restartConsent
  const restartIntentQuery = useQuery({
    enabled: Boolean(restartConsent),
    queryKey: ['catalyst-restart-intent'],
    queryFn: () => restartConsent?.get() ?? Promise.resolve(null),
    refetchInterval: 3_000,
    staleTime: 1_000
  })
  const restartIntent = restartIntentQuery.data ?? null

  const decideRestart = async (action: 'accept' | 'defer') => {
    if (!restartConsent || !restartIntent || restartDecisionPending) {
      return
    }

    setRestartDecisionPending(true)
    setRestartDecisionError(null)

    try {
      await restartConsent.decide({
        action,
        generation_hash: restartIntent.generation_hash,
        intent_id: restartIntent.intent_id
      })

      if (action === 'defer') {
        queryClient.setQueryData<CatalystRestartIntent>(
          ['catalyst-restart-intent'],
          { ...restartIntent, state: 'deferred' }
        )
        setRestartModalOpen(false)
      }
    } catch (error) {
      setRestartDecisionError(error instanceof Error ? error.message : String(error))
    } finally {
      setRestartDecisionPending(false)
    }
  }

  useEffect(() => {
    let cancelled = false

    if (!lucidModalOpen) {
      setLucidDocument(null)
      setLucidProjectionFailed(false)
      return () => {
        cancelled = true
      }
    }

    setLucidProjectionFailed(false)
    void projectLucidGestalt(lucidGestalt).then(document => {
      if (!cancelled) {
        setLucidDocument(document)
        setLucidProjectionFailed(document === null)
      }
    })

    return () => {
      cancelled = true
    }
  }, [lucidGestalt, lucidModalOpen])

  const toggleHaptics = () => {
    if (!hapticsMuted) {
      triggerHaptic('tap')
    }

    toggleHapticsMuted()

    if (hapticsMuted) {
      window.requestAnimationFrame(() => triggerHaptic('success'))
    }
  }

  // POSITIONAL toggles: each button shows/hides everything on its physical
  // side of the main zone (the layout tree collapses the whole side), so they
  // stay correct through flips and rearranges. $sidebarOpen ≙ left side,
  // $fileBrowserOpen ≙ right side. Never an active highlight — plain
  // show/hide affordances.
  const leftEdge = { open: sidebarOpen, toggle: toggleSidebarOpen }
  const rightEdge = { open: fileBrowserOpen, toggle: toggleFileBrowserOpen }

  const leftToolbarTools: TitlebarTool[] = [
    {
      actionId: 'view.toggleSidebar',
      icon: <Codicon name="layout-sidebar-left" />,
      id: 'sidebar',
      label: leftEdge.open ? t.titlebar.hideSidebar : t.titlebar.showSidebar,
      onSelect: () => {
        triggerHaptic('tap')
        leftEdge.toggle()
      }
    },
    {
      actionId: 'view.flipPanes',
      icon: <Codicon name="arrow-swap" />,
      id: 'flip-panes',
      label: t.titlebar.swapSidebarSides,
      onSelect: () => {
        triggerHaptic('tap')
        togglePanesFlipped()
      },
      title: t.titlebar.swapSidebarSidesTitle
    },
    ...leftTools
  ]

  const rightSidebarTool: TitlebarTool = {
    actionId: 'view.toggleRightSidebar',
    icon: <Codicon name="layout-sidebar-right" />,
    id: 'right-sidebar',
    label: rightEdge.open ? t.titlebar.hideRightSidebar : t.titlebar.showRightSidebar,
    onSelect: () => {
      triggerHaptic('tap')
      rightEdge.toggle()
    }
  }

  // Static system tools — always pinned to the screen's right edge.
  const systemTools: TitlebarTool[] = [
    {
      icon: <span className="text-[0.8125rem] leading-none">{lucidStatus.glyph}</span>,
      id: 'lucid-mcp-status',
      label: `LUCID: ${lucidStatus.connection}`,
      onSelect: () => {
        triggerHaptic(lucidStatus.signal === 'green' ? 'tap' : 'warning')
        setLucidModalOpen(true)
      },
      title: (
        <span className="whitespace-pre-line font-mono font-normal">
          {lucidGestalt}
        </span>
      )
    },
    {
      active: restartIntent?.state === 'deferred',
      className: restartIntent?.state === 'deferred' ? 'text-amber-500' : 'text-sky-400',
      hidden: !restartIntent,
      icon: <Codicon name="refresh" />,
      id: 'catalyst-restart-consent',
      label:
        restartIntent?.state === 'deferred'
          ? 'Catalyst restart deferred — open when ready'
          : 'Catalyst update ready — restart consent required',
      onSelect: () => {
        triggerHaptic('warning')
        setRestartDecisionError(null)
        setRestartModalOpen(true)
      },
      title: restartIntent ? (
        <span className="whitespace-pre-line font-mono font-normal">
          {`${restartIntent.state === 'deferred' ? '⚠️' : '⏳'} RUN · restart · catalyst · ${restartIntent.state}\n🔎 ${restartIntent.reason} · ${restartIntent.generation_hash}`}
        </span>
      ) : undefined
    },
    {
      className: 'group/tool',
      // Hover + held ⌘/Ctrl morphs the glyph into its reset form (see
      // LayoutGlyph) — the mod-click telegraphs itself before it happens.
      icon: <LayoutGlyph modHeld={modHeld} />,
      id: 'layout',
      label: t.titlebar.layoutEditor,
      onSelect: event => {
        if (event?.metaKey || event?.ctrlKey) {
          triggerHaptic('warning')
          resetLayoutTree()

          return
        }

        triggerHaptic('open')
        toggleLayoutEditMode()
      },
      title: t.titlebar.layoutEditorTitle
    },
    {
      active: hapticsMuted,
      icon: <Codicon name={hapticsMuted ? 'mute' : 'unmute'} />,
      id: 'haptics',
      label: hapticsMuted ? t.titlebar.unmuteHaptics : t.titlebar.muteHaptics,
      onSelect: toggleHaptics
    },
    {
      actionId: 'keybinds.openPanel',
      icon: <Codicon name="keyboard" />,
      id: 'keybinds',
      label: t.titlebar.openKeybinds,
      onSelect: () => {
        triggerHaptic('open')
        navigate(`${SETTINGS_ROUTE}?tab=keybinds`)
      }
    },
    {
      actionId: 'nav.settings',
      icon: <Codicon name="settings-gear" />,
      id: 'settings',
      label: t.titlebar.openSettings,
      onSelect: () => {
        triggerHaptic('open')
        onOpenSettings()
      }
    }
  ]

  // While a full-screen overlay (settings, command center, …) is open it should
  // visually own the window. These control clusters are `fixed` at a higher
  // z-index than the overlay card, so they'd otherwise bleed over it — hide them
  // and let the overlay's own chrome (close button, drag region) take over.
  if (isOverlayView(appViewForPath(location.pathname))) {
    return null
  }

  const visibleSystemTools = systemTools.filter(tool => !tool.hidden)
  const visiblePaneTools = tools.filter(tool => !tool.hidden)

  return (
    <>
      <Dialog onOpenChange={setRestartModalOpen} open={restartModalOpen && Boolean(restartIntent)}>
        <DialogContent fitContent onOpenAutoFocus={preventCloseButtonAutoFocus}>
          <DialogHeader>
            <DialogTitle>Catalyst update ready</DialogTitle>
            <DialogDescription>
              RUN prepared a new Catalyst generation and is waiting for your restart decision.
            </DialogDescription>
          </DialogHeader>
          {restartIntent && (
            <div className="space-y-3">
              <pre className="max-w-[min(42rem,82vw)] overflow-auto whitespace-pre-wrap rounded-md bg-(--ui-bg-quinary) p-3 font-mono text-xs text-(--ui-text-secondary)">
                {`${restartIntent.state === 'deferred' ? '⚠️' : '⏳'} RUN · restart · catalyst · ${restartIntent.state}\n🔎 ${restartIntent.reason}\n🔎 ${restartIntent.generation_hash}`}
              </pre>
              <p className="text-sm text-(--ui-text-secondary)">
                “Later” keeps this intent in the titlebar. You can reopen it and restart when your active work is safe.
              </p>
              {restartDecisionError && (
                <p className="text-sm text-(--ui-danger)">{restartDecisionError}</p>
              )}
            </div>
          )}
          <DialogFooter>
            <Button
              disabled={restartDecisionPending}
              onClick={() => void decideRestart('defer')}
              type="button"
              variant="outline"
            >
              Later
            </Button>
            <Button
              disabled={restartDecisionPending}
              onClick={() => void decideRestart('accept')}
              type="button"
            >
              {restartDecisionPending ? 'Recording decision…' : 'Restart now'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog onOpenChange={setLucidModalOpen} open={lucidModalOpen}>
        <DialogContent
          className="min-w-[min(42rem,92vw)]"
          fitContent
          onOpenAutoFocus={preventCloseButtonAutoFocus}
          resizable
        >
          <DialogHeader>
            <DialogTitle>LUCID</DialogTitle>
            <DialogDescription>
              Canonical GESTALT projected through the resident UGUI engine.
            </DialogDescription>
          </DialogHeader>
          {lucidDocument ? (
            <McpUguiDocument document={lucidDocument} />
          ) : (
            <p className={lucidProjectionFailed ? 'text-sm text-(--ui-danger)' : 'text-sm text-(--ui-text-secondary)'}>
              {lucidProjectionFailed ? 'Resident UGUI projector unavailable.' : 'Projecting through UGUI…'}
            </p>
          )}
          <DialogFooter>
            <Button
              onClick={() => {
                setLucidModalOpen(false)
                navigate(`${SKILLS_ROUTE}?tab=mcp`)
              }}
              type="button"
            >
              Open LUCID capabilities
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <div
        aria-label={t.shell.windowControls}
        className="fixed left-(--titlebar-controls-left) top-(--titlebar-controls-top) z-70 flex translate-y-0.5 flex-row items-center gap-x-1 pointer-events-auto select-none [-webkit-app-region:no-drag]"
      >
        {leftToolbarTools
          .filter(tool => !tool.hidden)
          .map(tool => (
            <TitlebarToolButton key={tool.id} navigate={navigate} tool={tool} />
          ))}
      </div>

      {/*
        Pane-scoped tools (preview's monitor / devtools / refresh / X) render
        as their own fixed cluster. AppShell sets --shell-preview-toolbar-gap
        to either the static cluster's width (file-browser closed → cluster
        sits flush against system tools) or the file-browser pane's width
        (file-browser open → cluster sits flush against the file-browser pane,
        i.e. at the preview pane's right edge). No margin hacks needed.
      */}
      {visiblePaneTools.length > 0 && (
        <div
          aria-label={t.shell.paneControls}
          className="fixed top-[calc(var(--titlebar-controls-top)+var(--right-rail-top-inset,0px))] right-[calc(var(--titlebar-tools-right)+var(--shell-preview-toolbar-gap,0))] z-70 flex flex-row items-center gap-x-1 pointer-events-auto select-none [-webkit-app-region:no-drag]"
        >
          {visiblePaneTools.map(tool => (
            <TitlebarToolButton key={tool.id} navigate={navigate} tool={tool} />
          ))}
        </div>
      )}

      <div
        aria-label={t.shell.appControls}
        className="fixed right-(--titlebar-tools-right) top-(--titlebar-controls-top) z-70 flex flex-row items-center justify-end gap-x-1 pointer-events-auto select-none [-webkit-app-region:no-drag]"
      >
        {visibleSystemTools.map(tool => (
          <TitlebarToolButton key={tool.id} navigate={navigate} tool={tool} />
        ))}
        <TitlebarToolButton navigate={navigate} tool={rightSidebarTool} />
      </div>
    </>
  )
}

function TitlebarToolButton({ navigate, tool }: { navigate: ReturnType<typeof useNavigate>; tool: TitlebarTool }) {
  // Titlebar actions never show an active background — state reads from the
  // icon itself (e.g. the mute/unmute glyph). aria-pressed still carries it
  // for a11y.
  const className = cn(
    titlebarButtonClass,
    'bg-transparent select-none [-webkit-app-region:no-drag]',
    tool.className
  )

  const tooltipLabel = tool.actionId ? (
    <TipKeybindLabel
      actionId={tool.actionId}
      text={typeof tool.title === 'string' ? tool.title : tool.label}
    />
  ) : (
    (tool.title ?? tool.label)
  )

  if (tool.href) {
    return (
      <Tip label={tooltipLabel}>
        <Button asChild className={className} size="icon-titlebar" variant="ghost">
          <a
            aria-label={tool.label}
            href={tool.href}
            onPointerDown={event => event.stopPropagation()}
            rel="noreferrer"
            target="_blank"
          >
            {tool.icon}
          </a>
        </Button>
      </Tip>
    )
  }

  return (
    <Tip label={tooltipLabel}>
      <Button
        aria-label={tool.label}
        aria-pressed={tool.active ?? undefined}
        className={className}
        disabled={tool.disabled}
        onClick={event => {
          if (tool.to) {
            navigate(tool.to)
          }

          tool.onSelect?.(event)
        }}
        onPointerDown={event => event.stopPropagation()}
        size="icon-titlebar"
        type="button"
        variant="ghost"
      >
        {tool.icon}
      </Button>
    </Tip>
  )
}
