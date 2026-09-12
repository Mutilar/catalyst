import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { $desktopBoot } from '@/store/boot'
import { $gatewaySwitching } from '@/store/gateway-switch'
import { $desktopOnboarding } from '@/store/onboarding'
import { setGatewayState } from '@/store/session'

import { BootFailureOverlay } from './boot-failure-overlay'
import { GatewayConnectingOverlay } from './gateway-connecting-overlay'
import { opaqueRegion, zoomFrame } from './splash-motion'

// Repro for the "remote gateway → stuck on CONNECTING, no way to settings"
// report. The connecting overlay (z-1200, full-screen, pointer-events on) used
// to be shown whenever `gatewayState !== 'open' && !boot.error`. The ONLY escape
// hatch — BootFailureOverlay, which has "Use local gateway" / "Sign in" /
// "Retry" — only renders when `boot.error` is set.
//
// useGatewayBoot only calls failDesktopBoot() (which sets boot.error) when the
// INITIAL boot() throws. After the first successful connect (bootCompleted),
// any later socket drop goes through scheduleReconnect(), which loops FOREVER
// against the dead remote. So gatewayState sits at 'closed'/'error' with
// boot.error null. The fix keeps the initial-boot overlay out of post-boot
// reconnects, leaving chat/settings usable while the reconnect loop runs.

function resetStores() {
  setGatewayState('idle')
  $gatewaySwitching.set(false)
  $desktopBoot.set({
    error: null,
    fakeMode: false,
    message: 'ready',
    phase: 'renderer.ready',
    progress: 100,
    running: false,
    timestamp: Date.now(),
    visible: false
  })
  $desktopOnboarding.set({
    configured: true,
    flow: { status: 'idle' },
    mode: 'oauth',
    providers: null,
    reason: null,
    requested: false,
    firstRunSkipped: false,
    manual: false,
    localEndpoint: false
  })
}

beforeEach(resetStores)
afterEach(cleanup)

// The connecting overlay renders "CONN" + a scrambled tail inside one
// uppercase span; match that node specifically so the recovery overlay's
// "Lost connection…" copy doesn't read as a false positive.
const isConnectingShown = () => Boolean(screen.queryByLabelText('Connecting'))

const isRecoveryShown = () =>
  Boolean(screen.queryByText(/use local gateway/i) || screen.queryByText(/retry/i) || screen.queryByText(/sign in/i))

describe('connecting overlay vs recovery surface', () => {
  it('hard initial-boot failure surfaces the recovery overlay (the working path)', async () => {
    // failDesktopBoot() ran: error set, gateway never opened.
    $desktopBoot.set({
      ...$desktopBoot.get(),
      error: 'Hermes backend did not become ready',
      running: false,
      visible: true
    })
    setGatewayState('error')

    await act(async () => {
      render(
        <>
          <GatewayConnectingOverlay />
          <BootFailureOverlay />
        </>
      )
    })

    expect(isRecoveryShown()).toBe(true)
    // Connecting overlay bows out when boot.error is set.
    expect(isConnectingShown()).toBe(false)
  })

  it('post-boot socket drops do not re-cover the app with the initial CONNECTING overlay', async () => {
    // 1. Initial boot succeeded: gateway opened, boot completed (no error).
    setGatewayState('open')

    let rerender!: (ui: React.ReactElement) => void
    await act(async () => {
      const result = render(
        <>
          <GatewayConnectingOverlay />
          <BootFailureOverlay />
        </>
      )

      rerender = result.rerender
    })

    expect(isConnectingShown()).toBe(false)

    // 2. The remote VPS socket drops (sleep/wake, remote restart, network).
    //    bootCompleted is true, so useGatewayBoot routes this through
    //    scheduleReconnect() — boot.error stays NULL.
    await act(async () => {
      setGatewayState('closed')
      rerender!(
        <>
          <GatewayConnectingOverlay />
          <BootFailureOverlay />
        </>
      )
    })

    // The initial-boot connecting overlay stays out of the way, so settings and
    // the composer remain reachable during the reconnect loop.
    expect(isConnectingShown()).toBe(false)
    expect(isRecoveryShown()).toBe(false)

    // 3. Reconnect loops against the dead remote: gatewayState bounces closed
    //    → error → closed. Until the escalation path sets boot.error, the app
    //    remains usable instead of modal-blocked.
    await act(async () => {
      setGatewayState('error')
      rerender!(
        <>
          <GatewayConnectingOverlay />
          <BootFailureOverlay />
        </>
      )
    })
    expect($desktopBoot.get().error).toBeNull()
    expect(isConnectingShown()).toBe(false)
    expect(isRecoveryShown()).toBe(false)
  })

  it('soft gateway switch keeps the shell — no fullscreen CONNECTING', async () => {
    setGatewayState('open')

    const { rerender } = render(
      <>
        <GatewayConnectingOverlay />
        <BootFailureOverlay />
      </>
    )

    await act(async () => {
      $gatewaySwitching.set(true)
      $desktopBoot.set({
        ...$desktopBoot.get(),
        running: true,
        visible: true,
        progress: 4,
        error: null
      })
      setGatewayState('closed')
      rerender(
        <>
          <GatewayConnectingOverlay />
          <BootFailureOverlay />
        </>
      )
    })

    expect(isConnectingShown()).toBe(false)
    expect(isRecoveryShown()).toBe(false)
  })

  it('FIX: once the prolonged reconnect raises a recoverable boot error, the recovery overlay takes over', async () => {
    // Mirrors what useGatewayBoot.scheduleReconnect() now does after ~45s of
    // failed post-boot reconnects: it calls failDesktopBoot(), flipping the UI
    // from the dead-end CONNECTING overlay to the recovery surface.
    setGatewayState('error')
    $desktopBoot.set({
      ...$desktopBoot.get(),
      error: 'Lost connection to the Hermes gateway and could not reconnect.',
      running: false,
      visible: true
    })

    await act(async () => {
      render(
        <>
          <GatewayConnectingOverlay />
          <BootFailureOverlay />
        </>
      )
    })

    // Escape hatch is now reachable; the connecting overlay bows out.
    expect(isRecoveryShown()).toBe(true)
    expect(screen.getByRole('button', { name: /gateway settings/i })).toBeTruthy()
    expect(isConnectingShown()).toBe(false)
  })
})

describe('WITNESS splash choreography', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    $desktopBoot.set({ ...$desktopBoot.get(), progress: 2, running: true, visible: true })
    setGatewayState('connecting')
    vi.stubGlobal('hermesDesktop', { getSplashIdentity: vi.fn().mockResolvedValue({ alias: 'brianhu', glyph: '🐧', image: 'data:image/svg+xml;base64,PHN2Zy8+' }) })
    vi.stubGlobal('Image', class { src = ''; decode = vi.fn().mockResolvedValue(undefined) })
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
      drawImage: vi.fn(), getImageData: () => ({ data: new Uint8ClampedArray(128 * 128 * 4).fill(255) }),
      measureText: () => ({ actualBoundingBoxAscent: 4, actualBoundingBoxDescent: 0 })
    } as never)
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
      left: 200, top: 100, width: 8, height: 8, right: 208, bottom: 108, x: 200, y: 100, toJSON: () => ({})
    })
  })
  afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

  async function tick(ms: number) { await act(async () => { await vi.advanceTimersByTimeAsync(ms) }) }
  function visiblePunctuation() {
    return Array.from(screen.getByLabelText('Connecting').querySelectorAll('span > span'))
      .filter(mark => (mark as HTMLElement).style.opacity === '1')
      .map(mark => mark.textContent).join('')
  }
  async function punctuation() {
    for (const text of ['.', '..', '...', '.', '..', '...']) {
      expect(visiblePunctuation()).toBe(text)
      await tick(600)
    }
  }

  it('loops dots until hydration settles, holds comma for one second, then holds the revealed identity for one second', async () => {
    await act(async () => { render(<GatewayConnectingOverlay />) })
    await punctuation()
    await act(async () => { setGatewayState('open') })
    await tick(2000)
    expect(screen.getByLabelText('Connecting').getAttribute('data-splash-phase')).toBe('punctuation')
    await act(async () => { $desktopBoot.set({ ...$desktopBoot.get(), running: false, progress: 100, visible: false }) })
    await tick(40)
    expect(visiblePunctuation()).toBe('...,')
    expect(screen.getByLabelText('Connecting').getAttribute('data-splash-phase')).toBe('comma')
    await tick(999)
    expect(screen.getByLabelText('Connecting').getAttribute('data-splash-phase')).toBe('comma')
    await tick(1)
    expect(screen.getByLabelText('BRIANHU 🐧')).toBeTruthy()
    await tick(700)
    await tick(999)
    expect(screen.getByLabelText('Connecting').getAttribute('data-splash-phase')).toBe('identity')
    await tick(1)
    expect(screen.getByLabelText('Connecting').getAttribute('data-splash-phase')).toBe('zoom')
    await tick(3700)
    expect(screen.getByLabelText('Connecting').getAttribute('data-splash-phase')).toBe('zoom')
    const alias = screen.getByLabelText('BRIANHU 🐧')
    expect(alias.style.opacity).not.toBe('0')
    expect(alias.parentElement?.style.transform).toContain('scale(')
    expect(alias.querySelector('img')?.style.opacity).toBe('0')
    await tick(180)
    expect(screen.getByLabelText('Connecting').getAttribute('data-splash-phase')).toBe('fade')
    const fadeTransform = alias.parentElement?.style.transform
    await tick(200)
    expect(screen.getByLabelText('Connecting').getAttribute('data-splash-phase')).toBe('fade')
    expect(alias.parentElement?.style.transform).not.toBe(fadeTransform)
    await tick(520)
    expect(isConnectingShown()).toBe(false)
  })

  it('skips zoom for reduced motion and yields immediately to boot errors', async () => {
    vi.stubGlobal('matchMedia', () => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
    await act(async () => { render(<GatewayConnectingOverlay />) })
    await punctuation()
    await act(async () => { setGatewayState('open'); $desktopBoot.set({ ...$desktopBoot.get(), running: false, progress: 100 }) })
    await tick(40)
    expect(screen.getByLabelText('Connecting').getAttribute('data-splash-phase')).toBe('comma')
    await tick(1000)
    expect(screen.getByLabelText('Connecting').getAttribute('data-splash-phase')).toBe('identity')
    await tick(1050)
    expect(screen.getByLabelText('Connecting').getAttribute('data-splash-phase')).toBe('fade')
    await tick(1)
    expect(isConnectingShown()).toBe(false)
    cleanup()
    $desktopBoot.set({ ...$desktopBoot.get(), running: true, progress: 2 })
    await act(async () => { render(<GatewayConnectingOverlay />) })
    await act(async () => { $desktopBoot.set({ ...$desktopBoot.get(), error: 'Boot failed' }) })
    expect(isConnectingShown()).toBe(false)
  })

  it('does not fabricate an identity or block a ready desktop when the capability is absent', async () => {
    vi.stubGlobal('hermesDesktop', {})
    await act(async () => { render(<GatewayConnectingOverlay />) })
    await punctuation()
    await act(async () => { setGatewayState('open'); $desktopBoot.set({ ...$desktopBoot.get(), running: false, progress: 100 }) })
    await tick(40)
    expect(screen.getByLabelText('Connecting').getAttribute('data-splash-identity')).toBe('unavailable')
    await tick(1000)
    await tick(520)
    expect(isConnectingShown()).toBe(false)
  })

  it('restarts the full comma hold if readiness is lost', async () => {
    await act(async () => { render(<GatewayConnectingOverlay />) })
    await act(async () => { setGatewayState('open'); $desktopBoot.set({ ...$desktopBoot.get(), running: false, progress: 100 }) })
    await tick(40)
    await tick(600)
    await act(async () => { setGatewayState('closed') })
    expect(screen.getByLabelText('Connecting').getAttribute('data-splash-phase')).toBe('punctuation')
    await tick(1200)
    expect(screen.queryByLabelText('BRIANHU 🐧')).toBeNull()
    await act(async () => { setGatewayState('open') })
    await tick(40)
    await tick(999)
    expect(screen.getByLabelText('Connecting').getAttribute('data-splash-phase')).toBe('comma')
    await tick(1)
    expect(screen.getByLabelText('BRIANHU 🐧')).toBeTruthy()
  })

  it('zooms geometrically from the measured period into an opaque square covering desktop and mobile', () => {
    const pixels = new Uint8ClampedArray(16 * 16 * 4)
    for (let row = 4; row < 14; row++) for (let column = 3; column < 13; column++) pixels[(row * 16 + column) * 4 + 3] = 255
    const region = opaqueRegion(pixels, 16)
    const start = { left: 200, top: 100, width: 8 }
    for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
      expect(zoomFrame(start, viewport, region, 0)).toEqual(start)
      const end = zoomFrame(start, viewport, region, 1)
      expect(end.width).toBeCloseTo(1.25 * Math.max(viewport.width, viewport.height) / region.size)
      expect(zoomFrame(start, viewport, region, 0.5).width).toBeCloseTo(start.width * (end.width / start.width) ** 0.25)
      const lateTravel = zoomFrame(start, viewport, region, 0.95).width - zoomFrame(start, viewport, region, 0.9).width
      const finalTravel = end.width - zoomFrame(start, viewport, region, 0.95).width
      expect(finalTravel).toBeGreaterThan(lateTravel)
      expect(zoomFrame(start, viewport, region, 0.25).width).toBeLessThan(zoomFrame(start, viewport, region, 0.5).width)
      expect(end.left + end.width * (region.x - region.size / 2)).toBeLessThanOrEqual(0.001)
      expect(end.top + end.width * (region.y - region.size / 2)).toBeLessThanOrEqual(0.001)
      expect(end.left + end.width * (region.x + region.size / 2)).toBeGreaterThanOrEqual(viewport.width - 0.001)
      expect(end.top + end.width * (region.y + region.size / 2)).toBeGreaterThanOrEqual(viewport.height - 0.001)
    }
    expect(() => opaqueRegion(new Uint8ClampedArray(16 * 16 * 4), 16)).toThrow('no opaque zoom target')
  })
})
