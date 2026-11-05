import { fireEvent, render, screen } from '@testing-library/react'
import { activity, ThinkingIndicator } from '../src/features/chat/ThinkingIndicator'
import type { Engine } from '../src/contract/engine'
import { ConfirmCard, ConfirmDetail, GuardrailCard, NoticeChip, QuestionCard } from '../src/features/chat/ActionCards'
import { ReasoningRibbon } from '../src/features/chat/ReasoningRibbon'
import type { ConfirmItem, GuardrailItem, QuestionItem } from '../src/state/store'
import { EngineProvider } from '../src/state/useEngine'

function fakeEngine() {
  const e = {
    send: vi.fn(), interrupt: vi.fn(), editMessage: vi.fn(() => null), confirm: vi.fn(),
    answer: vi.fn(), switchPersona: vi.fn(), subscribe: vi.fn(() => () => {}),
  }
  return { e, engine: e as unknown as Engine }
}

const confirm = (status: ConfirmItem['status']): ConfirmItem => ({
  kind: 'confirm', requestId: 'c1', title: 'Supprimer build/ ?', detail: '12 fichiers', risk: 'high', status, branch: 'main',
})
test("une confirmation périmée n'a plus de boutons et dit pourquoi", () => {
  const { engine } = fakeEngine()
  render(<EngineProvider engine={engine}><ConfirmCard item={confirm('expired')} /></EngineProvider>)
  expect(screen.getByText(/expirée/i)).toBeInTheDocument()
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
})

const question = (status: QuestionItem['status'], values?: Record<string, unknown>): QuestionItem => ({
  kind: 'question', requestId: 'q1', title: 'Préparer le déploiement', status, values, branch: 'main',
  fields: [
    { id: 'env', kind: 'choice', label: 'Environnement', options: ['staging', 'production'] },
    { id: 'tag', kind: 'text', label: 'Version' },
    { id: 'tests', kind: 'toggle', label: 'Lancer les tests' },
  ],
})

test('Autoriser et Refuser appellent le moteur avec la bonne décision', () => {
  const { e, engine } = fakeEngine()
  render(<EngineProvider engine={engine}><ConfirmCard item={confirm('pending')} /></EngineProvider>)
  fireEvent.click(screen.getByRole('button', { name: /autoriser/i }))
  expect(e.confirm).toHaveBeenCalledWith('c1', true)
})

test('refuser envoie false', () => {
  const { e, engine } = fakeEngine()
  render(<EngineProvider engine={engine}><ConfirmCard item={confirm('pending')} /></EngineProvider>)
  fireEvent.click(screen.getByRole('button', { name: /refuser/i }))
  expect(e.confirm).toHaveBeenCalledWith('c1', false)
})

test('une confirmation résolue affiche la décision, sans boutons', () => {
  const { engine } = fakeEngine()
  render(<EngineProvider engine={engine}><ConfirmCard item={confirm('denied')} /></EngineProvider>)
  expect(screen.getByText(/refusé/i)).toBeInTheDocument()
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
})

test("le formulaire bloque l'envoi tant qu'un champ texte est vide, puis envoie les valeurs", () => {
  const { e, engine } = fakeEngine()
  render(<EngineProvider engine={engine}><QuestionCard item={question('pending')} /></EngineProvider>)
  const submit = screen.getByRole('button', { name: /envoyer mes réponses/i })
  expect(submit).toBeDisabled()
  fireEvent.change(screen.getByLabelText('Version'), { target: { value: 'v0.3.0' } })
  fireEvent.click(screen.getByLabelText('Lancer les tests'))
  expect(submit).toBeEnabled()
  fireEvent.click(submit)
  expect(e.answer).toHaveBeenCalledWith('q1', { env: 'staging', tag: 'v0.3.0', tests: true })
})

test('un formulaire répondu affiche un récapitulatif', () => {
  const { engine } = fakeEngine()
  render(<EngineProvider engine={engine}><QuestionCard item={question('answered', { env: 'staging', tag: 'v1', tests: false })} /></EngineProvider>)
  expect(screen.getByText(/staging/)).toBeInTheDocument()
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
})

test('le garde-fou nomme la nature du blocage', () => {
  const item: GuardrailItem = { kind: 'guardrail', gKind: 'secret', message: 'valeur masquée', branch: 'main' }
  render(<GuardrailCard item={item} />)
  expect(screen.getByText(/secret masqué/i)).toBeInTheDocument()
  expect(screen.getByText('valeur masquée')).toBeInTheDocument()
})

test('les pastilles résument compression, cache et évaluation', () => {
  render(<>
    <NoticeChip item={{ kind: 'compression', savedTokens: 1840, branch: 'main' }} />
    <NoticeChip item={{ kind: 'cache', similarity: 0.94, branch: 'main' }} />
    <NoticeChip item={{ kind: 'eval', relevance: 0.91, faithfulness: 0.88, branch: 'main' }} />
    <NoticeChip item={{ kind: 'handoff', from: 'sensei', to: 'reviewer', branch: 'main' }} />
  </>)
  expect(screen.getByText(/1 840 tokens libérés/)).toBeInTheDocument()
  expect(screen.getByText(/94 %/)).toBeInTheDocument()
  expect(screen.getByText(/pertinence 91 %/i)).toBeInTheDocument()
  expect(screen.getByText(/CodeSensei → Relecteur/)).toBeInTheDocument()
})

const steps = [
  { id: 's1', thought: 'Je cherche', tool: 'rag.search', args: { q: 'x' }, observation: '5 passages', ms: 340, ok: true },
  { id: 's2', thought: 'Je lance', tool: 'sandbox.run', args: {}, observation: 'ZeroDivisionError', ms: 410, ok: false },
]

test('le raisonnement affiche étapes, durées et échecs dans l\'ordre', () => {
  render(<ReasoningRibbon steps={steps} active={false} />)
  const items = screen.getAllByRole('listitem')
  expect(items).toHaveLength(2)
  expect(items[0]).toHaveTextContent('Je cherche')
  expect(items[0]).toHaveTextContent('340 ms')
  expect(items[1]).toHaveTextContent(/échec/i)
})

test('le raisonnement se replie et se déplie', () => {
  render(<ReasoningRibbon steps={steps} active={false} />)
  const toggle = screen.getByRole('button', { name: /raisonnement/i })
  fireEvent.click(toggle)
  expect(screen.queryByRole('listitem')).not.toBeInTheDocument()
  expect(toggle).toHaveAttribute('aria-expanded', 'false')
  fireEvent.click(toggle)
  expect(screen.getAllByRole('listitem')).toHaveLength(2)
})

test("sans étape, le raisonnement n'affiche rien", () => {
  const { container } = render(<ReasoningRibbon steps={[]} active={false} />)
  expect(container).toBeEmptyDOMElement()
})

test("la demande d'accord de write_file montre le diff en couleur", () => {
  render(<ConfirmDetail text={'REPLACE /p/a.py (20 bytes). Changes:\n\n--- before\n+++ after\n@@ -1 +1 @@\n-x = 1\n+x = 2\n y = 3'} />)
  expect(screen.getByText(/REPLACE \/p\/a\.py/)).toBeInTheDocument()
  expect(screen.getByText('-x = 1').className).toContain('text-danger')
  expect(screen.getByText('+x = 2').className).toContain('text-ok')
  expect(screen.getByText('@@ -1 +1 @@').className).toContain('text-accent')
  expect(screen.getByText('+++ after').className).toContain('text-muted')
})

test('un détail sans diff reste un texte simple', () => {
  render(<ConfirmDetail text={'Supprimer build/ (12 fichiers)'} />)
  expect(screen.queryByLabelText('Modifications proposées')).not.toBeInTheDocument()
  expect(screen.getByText('Supprimer build/ (12 fichiers)')).toBeInTheDocument()
})

test('un outil MCP porte un badge, un outil interne non', () => {
  render(
    <ReasoningRibbon
      steps={[
        { id: 's1', tool: 'mcp_time_get_current_time', args: {}, observation: '12:00', ok: true, ms: 5 },
        { id: 's2', tool: 'read_file', args: { path: 'a.py' }, observation: 'ok', ok: true, ms: 3 },
      ]}
      active={false}
    />,
  )
  const items = screen.getAllByRole('listitem')
  expect(items[0]).toHaveTextContent('MCP')
  expect(items[1]).not.toHaveTextContent('MCP')
})

test('un relais vers un sous-agent du serveur affiche son rôle', () => {
  render(<NoticeChip item={{ kind: 'handoff', from: 'sensei', to: 'explorateur', branch: 'main' }} />)
  expect(screen.getByText(/CodeSensei → Explorateur/)).toBeInTheDocument()
})

test('le raisonnement reste ouvert pendant le tour puis se replie à la fin', () => {
  const { rerender } = render(<ReasoningRibbon steps={steps} active />)
  expect(screen.getAllByRole('listitem')).toHaveLength(2)
  rerender(<ReasoningRibbon steps={steps} active={false} took={12} />)
  expect(screen.queryByRole('listitem')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: /raisonnement · 2 étapes · 12 s/i })).toHaveAttribute('aria-expanded', 'false')
})

test("l'indicateur dit ce que fait l'agent : réflexion, outil, rédaction", () => {
  const turn = { id: 't', agent: 'sensei', text: '', steps: [], done: false, interrupted: false }
  expect(activity(turn)).toBe('Réflexion')
  expect(activity({ ...turn, steps: [{ id: 's', tool: 'read_file' }] })).toBe('Utilise read_file')
  expect(activity({ ...turn, text: 'Voici' })).toBe('Rédaction')
  render(<ThinkingIndicator label="Réflexion" since={Date.now()} />)
  expect(screen.getByRole('status', { name: /réflexion en cours/i })).toBeInTheDocument()
})
