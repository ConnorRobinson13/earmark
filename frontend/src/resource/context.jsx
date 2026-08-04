import { createContext, useContext } from 'react'
import { createResourceStore } from './store'
import { createHttpAdapter } from './httpAdapter'

/**
 * The store the app runs on in the browser. Tests provide their own via
 * `<ResourceProvider>`, which is the whole point of the adapter seam — a view
 * can render with no backend running.
 */
const browserStore = createResourceStore(createHttpAdapter())

const ResourceContext = createContext(browserStore)

export function ResourceProvider({ store, children }) {
  return <ResourceContext.Provider value={store}>{children}</ResourceContext.Provider>
}

export function useResourceStore() {
  return useContext(ResourceContext)
}
