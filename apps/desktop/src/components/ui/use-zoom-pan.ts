import {
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
  type RefObject,
  useCallback,
  useEffect,
  useRef,
  useState
} from 'react'

import { isSmartZoomWheel } from '@/lib/trackpad-gestures'

interface Transform {
  scale: number
  x: number
  y: number
}

const MIN_SCALE = 0.25
const MAX_SCALE = 8
const WHEEL_STEP = 1.1
const BUTTON_STEP = 1.25

const clamp = (scale: number) => Math.min(MAX_SCALE, Math.max(MIN_SCALE, scale))

/**
 * Headless pan/zoom transform. Wheel zooms toward the cursor, drag pans, buttons
 * zoom toward centre. Returns the transform style plus the surface handlers, so
 * any content (SVG, image, canvas) can be made pan/zoomable.
 */
export function useZoomPan(surfaceRef: RefObject<HTMLElement | null>) {
  const [transform, setTransform] = useState<Transform>({ scale: 1, x: 0, y: 0 })
  const drag = useRef<{ x: number; y: number } | null>(null)
  const [panning, setPanning] = useState(false)

  // Zoom toward (cx, cy), measured from the surface centre, keeping that point fixed.
  const zoomAt = useCallback((factor: number, cx = 0, cy = 0) => {
    setTransform(prev => {
      const scale = clamp(prev.scale * factor)
      const k = scale / prev.scale

      return { scale, x: cx - k * (cx - prev.x), y: cy - k * (cy - prev.y) }
    })
  }, [])

  const onWheel = useCallback(
    (event: WheelEvent) => {
      event.preventDefault()

      // macOS smart zoom (two-finger double-tap) → reset, not zoom-in.
      if (isSmartZoomWheel(event)) {
        setTransform({ scale: 1, x: 0, y: 0 })

        return
      }

      const rect = surfaceRef.current?.getBoundingClientRect()
      if (!rect) {
        return
      }
      const cx = event.clientX - rect.left - rect.width / 2
      const cy = event.clientY - rect.top - rect.height / 2

      zoomAt(event.deltaY < 0 ? WHEEL_STEP : 1 / WHEEL_STEP, cx, cy)
    },
    [surfaceRef, zoomAt]
  )

  useEffect(() => {
    const surface = surfaceRef.current
    if (!surface) {
      return
    }
    surface.addEventListener('wheel', onWheel, { passive: false })

    return () => surface.removeEventListener('wheel', onWheel)
  }, [onWheel, surfaceRef])

  const onPointerDown = useCallback((event: ReactPointerEvent) => {
    event.currentTarget.setPointerCapture(event.pointerId)
    setTransform(prev => {
      drag.current = { x: event.clientX - prev.x, y: event.clientY - prev.y }

      return prev
    })
    setPanning(true)
  }, [])

  const onPointerMove = useCallback((event: ReactPointerEvent) => {
    if (!drag.current) {
      return
    }

    const start = drag.current

    setTransform(prev => ({ ...prev, x: event.clientX - start.x, y: event.clientY - start.y }))
  }, [])

  const endPan = useCallback(() => {
    drag.current = null
    setPanning(false)
  }, [])

  const reset = useCallback(() => setTransform({ scale: 1, x: 0, y: 0 }), [])
  const zoomIn = useCallback(() => zoomAt(BUTTON_STEP), [zoomAt])
  const zoomOut = useCallback(() => zoomAt(1 / BUTTON_STEP), [zoomAt])

  const style: CSSProperties = {
    transform: `translate(${transform.x}px, ${transform.y}px) scale(${transform.scale})`
  }

  return {
    panning,
    reset,
    scale: transform.scale,
    stageProps: { onPointerDown, onPointerLeave: endPan, onPointerMove, onPointerUp: endPan },
    style,
    zoomIn,
    zoomOut
  }
}
