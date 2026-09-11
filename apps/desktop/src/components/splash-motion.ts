export interface OpaqueRegion {
  x: number
  y: number
  size: number
}

export function opaqueRegion(pixels: Uint8ClampedArray, size: number): OpaqueRegion {
  const squares = new Uint16Array(size * size)
  let best = 0
  let right = 0
  let bottom = 0

  for (let row = 0; row < size; row++) {
    for (let column = 0; column < size; column++) {
      const index = row * size + column

      if (pixels[index * 4 + 3] !== 255) {
        continue
      }

      squares[index] =
        row && column ? 1 + Math.min(squares[index - 1], squares[index - size], squares[index - size - 1]) : 1

      if (squares[index] > best) {
        best = squares[index]
        right = column + 1
        bottom = row + 1
      }
    }
  }

  if (best < 6) {
    throw new Error('Identity artwork has no opaque zoom target')
  }

  return { x: (right - best / 2) / size, y: (bottom - best / 2) / size, size: (best - 4) / size }
}

export function zoomFrame(
  start: { left: number; top: number; width: number },
  viewport: { width: number; height: number },
  region: OpaqueRegion,
  progress: number
) {
  const finalSize = Math.max(viewport.width, viewport.height) / region.size
  const width = start.width + (finalSize - start.width) * progress
  const targetX = start.left + start.width * region.x
  const targetY = start.top + start.width * region.y

  return {
    width,
    left: targetX + (viewport.width / 2 - targetX) * progress - width * region.x,
    top: targetY + (viewport.height / 2 - targetY) * progress - width * region.y
  }
}
