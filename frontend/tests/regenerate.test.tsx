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
      <button onClick={() => send('How do I run the tests?')}>send</button>
      <MessageList items={visibleTimeline(state, state.activeBranch)} />
    </>
  )
}

function answered(regenerates: boolean) {
  const f = fakeEngine(regenerates)
  render(<EngineProvider engine={f.engine}><Chat /></EngineProvider>)
  fireEvent.click(screen.getByText('send'))
  f.emit({ type: 'turn_start', turnId: 't1', agent: 'sensei' })
  expect(screen.queryByText('↻ Regenerate')).not.toBeInTheDocument() // not while answering
  f.emit({ type: 'token', turnId: 't1', text: 'pytest -q' })
  f.emit({ type: 'done', turnId: 't1', interrupted: false })
  return f
}

test('with the real server, Regenerate sends /again and shows the question again', () => {
  const { e } = answered(true)
  fireEvent.click(screen.getByText('↻ Regenerate'))
  expect(e.send).toHaveBeenLastCalledWith(expect.objectContaining({ text: '/again' }))
  expect(screen.getAllByText('How do I run the tests?')).toHaveLength(2)
})

test('in demo mode, Regenerate replays the same question', () => {
  const { e } = answered(false)
  fireEvent.click(screen.getByText('↻ Regenerate'))
  expect(e.send).toHaveBeenLastCalledWith(expect.objectContaining({ text: 'How do I run the tests?' }))
})
