import { useStore } from '@nanostores/react'
import { useEffect, useRef, useState } from 'react'

import { cn } from '@/lib/utils'
import { $desktopBoot } from '@/store/boot'
import { $gatewaySwitching } from '@/store/gateway-switch'
import { $gatewayState } from '@/store/session'

import { opaqueRegion, type OpaqueRegion, zoomFrame } from './splash-motion'

const PUNCTUATION = ['.', '..', '...', '...,']
const STEP_MS = 220
const REVEAL_MS = 1000
const ZOOM_MS = 1800
const FADE_MS = 520
type Phase = 'punctuation' | 'waiting' | 'identity' | 'zoom' | 'covered' | 'fade' | 'gone'
type Identity = { alias: string; glyph: string; image: string; region: OpaqueRegion }

// Dev affordance: a warm Cmd+R reconnects almost instantly, so the overlay
// only flashes. Load with `?connecting=1` to force a looping preview.
function forcedPreview(): boolean {
  if (!import.meta.env.DEV || typeof window === 'undefined') {
    return false
  }

  try {
    return new URLSearchParams(window.location.search).get('connecting') === '1'
  } catch {
    return false
  }
}

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && Boolean(window.matchMedia?.('(prefers-reduced-motion: reduce)').matches)
}

export function GatewayConnectingOverlay() {
  const gatewayState = useStore($gatewayState)
  const boot = useStore($desktopBoot)
  const gatewaySwitching = useStore($gatewaySwitching)
  const [previewing] = useState(forcedPreview)
  const [reduce, setReduce] = useState(prefersReducedMotion)
  const [phase, setPhase] = useState<Phase>('punctuation')
  const [step, setStep] = useState(0)
  const [identity, setIdentity] = useState<Identity | null>(null)
  const [prepared, setPrepared] = useState(false)
  const [painted, setPainted] = useState(false)
  const [previewReady, setPreviewReady] = useState(false)
  const marker = useRef<HTMLImageElement>(null)
  const zoomImage = useRef<HTMLImageElement>(null)
  const wordmark = useRef<HTMLDivElement>(null)
  const coldBootDoneRef = useRef(false)

  if (!boot.running && boot.progress >= 100 && !boot.error) {
    coldBootDoneRef.current = true
  }

  // The full-screen connecting overlay is for initial boot only. After a
  // healthy boot, flaky networks / sleep-wake can drop the socket and flip the
  // gateway state back to closed/error while the app reconnects. Do not cover
  // the chat then — users should still be able to type drafts, open settings,
  // and recover instead of staring at a modal CONNECTING screen.
  const initialBootActive = boot.visible || boot.running || boot.progress < 100

  const connecting = !coldBootDoneRef.current && !gatewaySwitching && !boot.error && initialBootActive

  // Latches once we've actually shown the overlay, so the brief frame where
  // gatewayState flips to "open" (connecting -> false) before the exit phase
  // kicks in doesn't unmount us and cause a flash.
  const shownRef = useRef(false)

  if (previewing || connecting) {
    shownRef.current = true
  }

  const visible = previewing || (shownRef.current && !gatewaySwitching && !boot.error && phase !== 'gone')
  const ready = gatewayState === 'open' && !boot.running && boot.progress >= 100 && !boot.error

  useEffect(() => {
    const media = window.matchMedia?.('(prefers-reduced-motion: reduce)')
    const update = () => setReduce(Boolean(media?.matches))
    media?.addEventListener?.('change', update)

    return () => media?.removeEventListener?.('change', update)
  }, [])

  useEffect(() => {
    if (!visible) {
      return
    }

    let cancelled = false

    const timeout = window.setTimeout(() => {
      cancelled = true
      setPrepared(true)
    }, 5000)

    const load = async () => {
      try {
        const value = window.hermesDesktop?.getSplashIdentity
          ? await window.hermesDesktop.getSplashIdentity()
          : previewing ? await fetch('/__splash-identity').then(response => response.ok ? response.json() : null) : null

        if (
          !value ||
          !/^[a-z][a-z0-9_-]{0,31}$/i.test(value.alias) ||
          !value.image.startsWith('data:image/svg+xml;base64,')
        ) {
          return
        }

        const image = new Image()
        image.src = value.image
        await image.decode()
        const canvas = document.createElement('canvas')
        canvas.width = canvas.height = 128
        const context = canvas.getContext('2d', { willReadFrequently: true })

        if (!context) {
          return
        }

        context.drawImage(image, 0, 0, 128, 128)
        const region = opaqueRegion(context.getImageData(0, 0, 128, 128).data, 128)
        await document.fonts?.ready

        if (!cancelled) {
          setIdentity({ ...value, region })
        }
      } finally {
        if (!cancelled) {
          setPrepared(true)
          window.clearTimeout(timeout)
        }
      }
    }

    void load().catch(() => undefined)

    return () => {
      cancelled = true
      window.clearTimeout(timeout)
    }
  }, [visible, previewing])

  useEffect(() => {
    if (!previewing) {
      return
    }

    const timer = window.setTimeout(() => setPreviewReady(true), 2600)

    return () => window.clearTimeout(timer)
  }, [previewing])

  useEffect(() => {
    if (!visible || phase !== 'punctuation') {
      return
    }

    const timer = window.setTimeout(() => {
      if (step < PUNCTUATION.length - 1) {
        setStep(step + 1)
      } else {
        setPhase('waiting')
      }
    }, STEP_MS)

    return () => window.clearTimeout(timer)
  }, [visible, phase, step])

  useEffect(() => {
    if (!(previewing ? previewReady : ready)) {
      setPainted(false)

      return
    }

    let second = 0

    const first = requestAnimationFrame(() => {
      second = requestAnimationFrame(() => setPainted(true))
    })

    return () => {
      cancelAnimationFrame(first)
      cancelAnimationFrame(second)
    }
  }, [ready, previewing, previewReady])

  useEffect(() => {
    if (phase === 'waiting' && prepared && painted) {
      setPhase(identity ? 'identity' : 'fade')
    }
  }, [phase, prepared, painted, identity])

  useEffect(() => {
    if (phase !== 'identity' || !visible) {
      return
    }

    const element = wordmark.current

    if (!element) {
      return
    }

    const fit = () => {
      element.style.fontSize = '40px'
      const width = element.getBoundingClientRect().width

      if (width > window.innerWidth - 48) {
        element.style.fontSize = `${(40 * (window.innerWidth - 48)) / width}px`
      }
    }

    fit()
    window.addEventListener('resize', fit)
    const timer = window.setTimeout(() => setPhase(reduce ? 'fade' : 'zoom'), REVEAL_MS)

    return () => {
      window.clearTimeout(timer)
      window.removeEventListener('resize', fit)
    }
  }, [phase, reduce, visible])

  useEffect(() => {
    if (phase !== 'zoom' || !identity || !marker.current || !zoomImage.current || !visible) {
      return
    }

    if (reduce) {
      setPhase('fade')

      return
    }

    const start = marker.current.getBoundingClientRect()
    const image = zoomImage.current
    let first: number | undefined
    let frame = 0

    const paint = (now: number) => {
      first ??= now
      const progress = Math.min(1, (now - first) / ZOOM_MS)
      const rect = zoomFrame(start, { width: window.innerWidth, height: window.innerHeight }, identity.region, progress)
      Object.assign(image.style, {
        left: `${rect.left}px`,
        top: `${rect.top}px`,
        width: `${rect.width}px`,
        height: `${rect.width}px`
      })

      if (progress < 1) {
        frame = requestAnimationFrame(paint)
      } else {
        setPhase('covered')
      }
    }

    frame = requestAnimationFrame(paint)

    return () => cancelAnimationFrame(frame)
  }, [phase, identity, reduce, visible])

  useEffect(() => {
    if (phase === 'covered') {
      let second = 0

      const first = requestAnimationFrame(() => {
        second = requestAnimationFrame(() => setPhase('fade'))
      })

      return () => {
        cancelAnimationFrame(first)
        cancelAnimationFrame(second)
      }
    }

    if (phase === 'fade') {
      const timer = window.setTimeout(() => setPhase('gone'), reduce ? 0 : FADE_MS)

      return () => window.clearTimeout(timer)
    }
  }, [phase, reduce])

  // Boot failed — BootFailureOverlay owns the screen; don't linger behind it.
  if (boot.error && !previewing) {
    return null
  }

  // Real connect: once the fade finishes, get out of the way for good.
  if (phase === 'gone') {
    return null
  }

  // Never showed (e.g. gateway already up on a warm reload) — stay out.
  if (!previewing && !connecting && !shownRef.current) {
    return null
  }

  if (!visible) {
    return null
  }

  const revealed = identity && !['punctuation', 'waiting'].includes(phase)
  const zooming = ['zoom', 'covered', 'fade'].includes(phase) && !reduce && identity

  return (
    <div
      aria-busy={!painted}
      aria-label="Connecting"
      className={cn(
        'fixed inset-0 z-[1200] grid place-items-center overflow-hidden bg-(--ui-chat-surface-background)',
        phase === 'fade' && 'pointer-events-none'
      )}
      data-splash-identity={prepared ? (identity ? 'ready' : 'unavailable') : 'loading'}
      data-splash-phase={phase}
      style={{
        opacity: phase === 'fade' ? 0 : 1,
        transition: phase === 'fade' ? `opacity ${reduce ? 0 : FADE_MS}ms linear` : 'none'
      }}
    >
      {revealed ? (
        <div
          aria-label={`${identity.alias.toUpperCase()} ${identity.glyph}`}
          className="whitespace-nowrap font-mono font-medium text-(--theme-primary)"
          ref={wordmark}
          style={{ fontSize: 40, letterSpacing: 0, lineHeight: 1, opacity: zooming ? 0 : 1 }}
        >
          {identity.alias.toUpperCase()}
          <img
            alt=""
            className="inline-block"
            ref={marker}
            src={identity.image}
            style={{ width: '0.22em', height: '0.22em', marginLeft: '0.04em', verticalAlign: 'baseline' }}
          />
        </div>
      ) : (
        <span
          aria-hidden="true"
          className="font-mono text-4xl text-(--theme-primary)"
          style={{ width: '4ch', letterSpacing: 0 }}
        >
          {PUNCTUATION[step]}
        </span>
      )}
      {identity && (
        <img
          alt=""
          aria-hidden="true"
          className="pointer-events-none absolute max-w-none"
          ref={zoomImage}
          src={identity.image}
          style={{ display: zooming ? 'block' : 'none', left: 0, top: 0, width: 0, height: 0 }}
        />
      )}
    </div>
  )
}
