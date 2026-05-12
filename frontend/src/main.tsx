/**
 * main.tsx — the entry point. Wires providers around the app.
 *
 * TEACHING NOTE: Provider layering.
 *
 * React providers form a stack. Anything lower in the tree can consume
 * anything provided above it. The rule: providers that are needed
 * globally go here; providers that are needed by a subtree go on that
 * subtree's root.
 *
 * QueryClientProvider (from TanStack Query) must wrap the whole app
 * because any component can call useQuery or useMutation.
 *
 * ActorProvider wraps the app for the same reason — any component can
 * call useActor().
 *
 * StrictMode renders every component twice in development to surface
 * side effects in render. Leave it on — it catches real bugs.
 */

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ActorProvider } from './context/ActorContext'
import { App } from './App'
import './App.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 30_000,
    },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ActorProvider>
        <App />
      </ActorProvider>
    </QueryClientProvider>
  </StrictMode>,
)
