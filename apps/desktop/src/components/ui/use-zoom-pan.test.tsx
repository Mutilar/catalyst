import { act, cleanup, render } from '@testing-library/react'
import { useRef } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useZoomPan } from './use-zoom-pan'

function ZoomSurface() {
  const ref = useRef<HTMLDivElement>(null)
  const { stageProps } = useZoomPan(ref)

  return <div data-testid="surface" ref={ref} {...stageProps} />
}

describe('useZoomPan', () => {
  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
  })

  it('owns wheel cancellation through a non-passive native listener', () => {
    const addEventListener = vi.spyOn(HTMLDivElement.prototype, 'addEventListener')
    const { getByTestId, unmount } = render(<ZoomSurface />)
    const surface = getByTestId('surface')

    const wheelRegistration = addEventListener.mock.calls.find(
      ([type], index) => type === 'wheel' && addEventListener.mock.contexts[index] === surface
    )

    expect(wheelRegistration?.[2]).toEqual({ passive: false })

    const event = new WheelEvent('wheel', { cancelable: true, deltaY: 1 })
    act(() => surface.dispatchEvent(event))
    expect(event.defaultPrevented).toBe(true)

    const removeEventListener = vi.spyOn(surface, 'removeEventListener')

    unmount()
    expect(removeEventListener).toHaveBeenCalledWith('wheel', wheelRegistration?.[1])
  })
})
