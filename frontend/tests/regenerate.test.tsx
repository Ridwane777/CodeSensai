import { act, fireEvent, render, screen } from '@testing-library/react'
import type { Engine } from '../src/contract/engine'
import type { EngineEvent } from '../src/contract/events'
import { MessageList } from '../src/features/chat/MessageList'
import { visibleTimeline } from '../src/state/store'
import { EngineProvider, useEngine } from '../src/state/useEngine'

function fakeEngine(regenerates: boolean) {
  let listener: (e: EngineEvent) => void = () => {}
  const e = {
    regenerates,
    send: vi.fn(), interrupt: vi.fn(), editMessage: vi.fn(() => null), confirm: vi.fn(),
    answer: vi.fn(), switchPersona: vi.fn(),
    subscribe: vi.fn((l: (ev: EngineEvent) => void) => { listener = l; return () => {} }),
  }
  return { e, engine: e as unknown as Engine, emit: (ev: EngineEvent) => act(() => listener(ev)) }
}

function Chat() {
  const { state, send } = useEngine()
  return (
    <>
      <button onClick={() => send('Comment lancer les tests ?')}>envoyer</button>
      <MessageList items={visibleTimeline(state, state.activeBranch)} />
    </>
  )
}

function answered(regenerates: boolean) {
  const f = fakeEngine(regenerates)
  render(<EngineProvider engine={f.engine}><Chat /></EngineProvider>)
  fireEvent.click(screen.getByText('envoyer'))
  f.emit({ type: 'turn_start', turnId: 't1', agent: 'sensei' })
  expect(screen.queryByText('↻ Régénérer')).not.toBeInTheDocument() // pas pendant la réponse
  f.emit({ type: 'token', turnId: 't1', text: 'pytest -q' })
  f.emit({ type: 'done', turnId: 't1', interrupted: false })
  return f
}

test('avec le serveur réel, Régénérer envoie /again et réaffiche la question', () => {
  const { e } = answered(true)
  fireEvent.click(screen.getByText('↻ Régénérer'))
  expect(e.send).toHaveBeenLastCalledWith(expect.objectContaining({ text: '/again' }))
  expect(screen.getAllByText('Comment lancer les tests ?')).toHaveLength(2)
})

test('en démonstration, Régénérer rejoue la même question', () => {
  const { e } = answered(false)
  fireEvent.click(screen.getByText('↻ Régénérer'))
  expect(e.send).toHaveBeenLastCalledWith(expect.objectContaining({ text: 'Comment lancer les tests ?' }))
})
