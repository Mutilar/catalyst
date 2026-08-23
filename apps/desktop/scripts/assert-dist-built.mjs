// Build-time guard: refuse to hand a half-built renderer to electron-builder.
//
// `npm run pack` / `npm run dist*` are `npm run build && npm run builder`.
// If the `build` step (tsc -b && vite build) fails but packaging proceeds
// anyway — a stale checkout that fails typecheck, an interrupted vite build,
// or npm not short-circuiting `&&` in some shells — electron-builder happily
// packages an app with an empty or missing `dist/`. The result launches but
// blank-pages with `ERR_FILE_NOT_FOUND` for dist/index.html, with no clue why.
//
// This runs at the tail of `build`, after vite build, so any packaging path
// inherits it. It fails loud and early instead of shipping a broken bundle.
// See issues #39484 (renderer blank page) and #41327 / #39472 (dashboard 404).

import { existsSync, statSync, readdirSync } from "fs"
import { join, resolve } from "path"
import { isMain } from "./utils.mjs"

// Pure check — returns { ok: true } or { ok: false, error: "..." }.
// Kept side-effect-free so it can be unit tested without spawning a process.
export function checkDistBuilt(distDir) {
  if (!existsSync(distDir) || !statSync(distDir).isDirectory()) {
    return { ok: false, error: `no dist directory at ${distDir}` }
  }

  const indexHtml = join(distDir, "index.html")
  if (!existsSync(indexHtml) || !statSync(indexHtml).isFile()) {
    return { ok: false, error: `dist/index.html is missing at ${indexHtml}` }
  }
  if (statSync(indexHtml).size === 0) {
    return { ok: false, error: `dist/index.html is empty at ${indexHtml}` }
  }

  // index.html alone isn't enough — vite emits hashed JS into dist/assets.
  // An index.html with no script bundle still blank-pages.
  const assetsDir = join(distDir, "assets")
  const hasAssets =
    existsSync(assetsDir) &&
    statSync(assetsDir).isDirectory() &&
    readdirSync(assetsDir).some(name => name.endsWith(".js"))
  if (!hasAssets) {
    return { ok: false, error: `dist/assets has no built JS bundle (expected vite output under ${assetsDir})` }
  }

  for (const name of ["electron-main.mjs", "electron-preload.js"]) {
    const output = join(distDir, name)
    if (!existsSync(output) || !statSync(output).isFile()) {
      return { ok: false, error: `dist/${name} is missing at ${output}` }
    }
    if (statSync(output).size === 0) {
      return { ok: false, error: `dist/${name} is empty at ${output}` }
    }
  }

  for (const name of [
    "ugui_gestalt_wasm.js",
    "ugui_gestalt_wasm_bg.wasm",
    "catalyst_wasm.js",
    "catalyst_wasm_bg.wasm",
  ]) {
    const output = join(distDir, "wasm", name)
    if (!existsSync(output) || !statSync(output).isFile() || statSync(output).size === 0) {
      return { ok: false, error: `dist/wasm/${name} is missing or empty at ${output}` }
    }
  }

  return { ok: true }
}

function main() {
  const desktopRoot = resolve(import.meta.dirname, "..")
  const distDir = join(desktopRoot, "dist")
  const result = checkDistBuilt(distDir)

  if (!result.ok) {
    console.error(`\n✗ assert-dist-built: ${result.error}`)
    console.error("  The renderer bundle is missing or incomplete, so packaging")
    console.error("  would produce an app that launches to a blank page.")
    console.error("  Re-run the build and check the tsc/vite output above for the")
    console.error("  real failure, then package again:")
    console.error(`    cd ${desktopRoot} && npm run build\n`)
    process.exit(1)
  }

  console.log("✓ assert-dist-built: renderer + electron main + preload present")
}

if (isMain(import.meta.url)) {
  main()
}

export default { checkDistBuilt }
