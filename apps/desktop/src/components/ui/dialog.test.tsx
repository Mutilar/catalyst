import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { Dialog, DialogContent, DialogTitle } from './dialog'

describe('DialogContent geometry', () => {
  afterEach(cleanup)

  it('adds only geometry behavior when resizable is enabled', () => {
    render(
      <Dialog defaultOpen>
        <DialogContent resizable>
          <DialogTitle>Resizable</DialogTitle>
        </DialogContent>
      </Dialog>
    )

    const dialog = document.querySelector('[data-slot="dialog-content"]')

    expect(dialog?.className).toContain('resize')
    expect(dialog?.className).toContain('max-w-[calc(100vw-2rem)]')
    expect(dialog?.className).toContain('max-h-[calc(100vh-2rem)]')
  })
})