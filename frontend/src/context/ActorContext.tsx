/**
 * ActorContext — who is currently operating the dashboard?
 *
 * TEACHING NOTE: This is the pre-auth pattern. We have no real login,
 * so we ask the user their name/email once, store it in localStorage,
 * and thread it through every mutating API call as the `actor` field.
 * The audit log in the database then records it.
 *
 * When CWL OIDC is added, the swap is surgical:
 *   - Remove the localStorage read/write
 *   - Replace `actor` with `user.email` from the OIDC token
 *   - The rest of the codebase doesn't know or care
 *
 * React Context is the right tool here because "who is the actor"
 * is *ambient* state — needed in many components but owned by none
 * of them. The alternative (prop drilling) would mean passing `actor`
 * through App → QualifierTable → DrawPanel → ... just to get it to
 * the component that calls api.draw(). That's painful and fragile.
 *
 * WHEN NOT to use Context: data that changes frequently (every keystroke,
 * every scroll position) causes all context consumers to re-render.
 * Actor name never changes during a session, so Context is safe here.
 */

import { createContext, useContext, useState, useCallback, type ReactNode } from 'react'

interface ActorContextValue {
  actor: string | null
  setActor: (name: string) => void
  clearActor: () => void
}

const STORAGE_KEY = 'parking_perks_actor'

const ActorContext = createContext<ActorContextValue | null>(null)

export function ActorProvider({ children }: { children: ReactNode }) {
  const [actor, setActorState] = useState<string | null>(
    () => localStorage.getItem(STORAGE_KEY),
  )

  const setActor = useCallback((name: string) => {
    localStorage.setItem(STORAGE_KEY, name)
    setActorState(name)
  }, [])

  const clearActor = useCallback(() => {
    localStorage.removeItem(STORAGE_KEY)
    setActorState(null)
  }, [])

  return (
    <ActorContext.Provider value={{ actor, setActor, clearActor }}>
      {children}
    </ActorContext.Provider>
  )
}

export function useActor(): ActorContextValue {
  const ctx = useContext(ActorContext)
  if (!ctx) throw new Error('useActor must be used inside ActorProvider')
  return ctx
}
