import { cleanup, render } from '@testing-library/react'
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
    const { getByTestId } = render(<ZoomSurface />)
    const wheelRegistration = addEventListener.mock.calls.find(([type]) => type === 'wheel')

    expect(wheelRegistration?.[2]).toEqual({ passive: false })

    const event = new WheelEvent('wheel', { cancelable: true, deltaY: 1 })
    getByTestId('surface').dispatchEvent(event)
    expect(event.defaultPrevented).toBe(true)
  })
})
