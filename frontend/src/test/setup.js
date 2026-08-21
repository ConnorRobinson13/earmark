/**
 * Give the test environment a working `localStorage`.
 *
 * Node 22 added its own Web Storage globals, gated behind
 * `--localstorage-file`. Without that flag `globalThis.localStorage` is a
 * getter that warns and answers `undefined` — and because the property already
 * exists, vitest's jsdom environment leaves it alone rather than installing
 * jsdom's. The result on Node 26 is a suite where `localStorage` is present,
 * undefined, and takes `NetWorth.test.jsx` down with it at
 * `localStorage.clear()`.
 *
 * The app already survives this: every access is inside a try/catch, so the
 * projection dials just stopped persisting under test and nothing said so.
 * Handing the tests a real store means that path is exercised rather than
 * silently skipped.
 */
class MemoryStorage {
  #entries = new Map()

  get length() { return this.#entries.size }
  key(i) { return [...this.#entries.keys()][i] ?? null }
  getItem(k) { return this.#entries.has(String(k)) ? this.#entries.get(String(k)) : null }
  setItem(k, v) { this.#entries.set(String(k), String(v)) }
  removeItem(k) { this.#entries.delete(String(k)) }
  clear() { this.#entries.clear() }
}

for (const name of ['localStorage', 'sessionStorage']) {
  if (!globalThis[name]) {
    Object.defineProperty(globalThis, name, {
      value: new MemoryStorage(),
      configurable: true,
      writable: true,
    })
  }
}
