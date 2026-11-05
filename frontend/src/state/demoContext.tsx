import { createContext, useContext, useReducer, type Dispatch, type ReactNode } from 'react'
import { demoReducer, initialDemo, type DemoAction, type DemoData } from './demoData'

const Ctx = createContext<{ data: DemoData; dispatch: Dispatch<DemoAction> } | null>(null)

export function DemoDataProvider({ children }: { children: ReactNode }) {
  const [data, dispatch] = useReducer(demoReducer, initialDemo)
  return <Ctx.Provider value={{ data, dispatch }}>{children}</Ctx.Provider>
}

export function useDemo() {
  const c = useContext(Ctx)
  if (!c) throw new Error('useDemo doit être utilisé dans <DemoDataProvider>')
  return c
}
