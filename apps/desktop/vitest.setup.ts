import { configure } from '@testing-library/react'

// React 19 + Testing Library 16: opt into the act environment so render(),
// fireEvent(), and findBy* queries automatically flush state updates without
// spurious "not wrapped in act(...)" warnings.
;(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true

// findBy*/waitFor default to a 1000ms deadline — too tight for async-heavy
// panels (radix menus, refetch chains) when the full suite runs under xdist
// CPU contention in CI. Success still resolves the instant the node appears;
// the wider deadline only absorbs a starved runner, killing timing flakes.
configure({ asyncUtilTimeout: 5000 })

function memoryStorage(): Storage {
  const values = new Map<string, string>()

  return {
    clear: () => values.clear(),
    getItem: key => values.get(key) ?? null,
    key: index => [...values.keys()][index] ?? null,
    get length() {
      return values.size
    },
    removeItem: key => values.delete(key),
    setItem: (key, value) => values.set(key, String(value))
  }
}

// Node 26 exposes configurable global localStorage/sessionStorage accessors
// whose value is undefined unless --localstorage-file is set. Vitest's jsdom
// global inherits those accessors, shadowing jsdom's origin-scoped Storage and
// breaking every persistence test. Rebind only when the environment did not
// provide a usable implementation; browsers and older Node releases are left
// untouched.
for (const name of ['localStorage', 'sessionStorage'] as const) {
  let storage: Storage | undefined

  try {
    storage = globalThis.window?.[name]
  } catch {
    storage = undefined
  }

  if (!storage) {
    Object.defineProperty(globalThis, name, { configurable: true, value: memoryStorage() })
  }
}
