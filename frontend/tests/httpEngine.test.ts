import { HttpEngine, SseParser } from '../src/engine/httpEngine'
import type { EngineEvent } from '../src/contract/events'

const line = (e: unknown) => `data: ${JSON.stringify(e)}\n\n`

test("l'analyseur SSE recompose un événement coupé entre deux morceaux", () => {
  const p = new SseParser()
  const full = line({ type: 'token', text: 'a' })
  expect(p.push(full.slice(0, 10))).toEqual([])
  expect(p.push(full.slice(10))).toEqual([{ type: 'token', text: 'a' }])
})

test('ignore les lignes invalides, les objets sans type et les commentaires', () => {
  const p = new SseParser()
  const out = p.push(`: ping\n\ndata: pas du json\n\n${line({ nope: 1 })}${line({ type: 'error', message: 'x' })}`)
  expect(out).toEqual([{ type: 'error', message: 'x' }])
})

test('accepte les fins de ligne \\r\\n', () => {
  expect(new SseParser().push('data: {"type":"token","text":"a"}\r\n\r\n')).toEqual([{ type: 'token', text: 'a' }])
})

/** Un faux sensai-web : sessions, flux SSE scriptés, confirmation, interruption, bifurcation. */
function fakeServer() {
  const calls: { method: string; path: string; body: unknown; auth: string | null }[] = []
  let sessions = 0
  const state = {
    /** Événements renvoyés pour le prochain message (`hang` : le flux reste ouvert). */
    events: [{ type: 'token', text: 'Bonjour.' }, { type: 'done', reason: 'final_answer' }] as unknown[],
    hang: false,
    confirmStatus: 204,
    answerStatus: 204,
    unauthorized: false,
    forkFails: false,
    streamController: null as ReadableStreamDefaultController<Uint8Array> | null,
  }
  const json = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
  const fetchFn = vi.fn(async (url: string, init?: RequestInit) => {
    const path = url.replace('http://api.test', '')
    const body = init?.body ? JSON.parse(String(init.body)) : undefined
    const auth = new Headers(init?.headers).get('Authorization')
    calls.push({ method: init?.method ?? 'GET', path, body, auth })
    if (init?.signal?.aborted) throw Object.assign(new Error('aborted'), { name: 'AbortError' })
    if (state.unauthorized) return json({ error: 'Authentification requise', code: 'UNAUTHORIZED' }, 401)
    if (path === '/api/sessions' && (init?.method ?? 'GET') === 'GET')
      return json([{ session_id: 'OLD', title: 'Hier', updated_at: '2026-10-28T18:00:00+00:00', message_count: 4 }])
    if (path === '/api/sessions/OLD')
      return json({ session_id: 'OLD', messages: [
        { role: 'user', content: 'q1' }, { role: 'assistant', content: 'r1' },
        { role: 'user', content: 'q2' }, { role: 'assistant', content: 'r2' },
      ] })
    if (path === '/api/sessions') return json({ session_id: `S${++sessions}` }, 201)
    if (path.endsWith('/messages')) {
      const enc = new TextEncoder()
      return new Response(
        new ReadableStream<Uint8Array>({
          start(c) {
            state.streamController = c
            for (const e of state.events) c.enqueue(enc.encode(line(e)))
            if (!state.hang) c.close()
          },
        }),
      )
    }
    if (path.endsWith('/interrupt')) {
      const c = state.streamController
      if (c) {
        c.enqueue(new TextEncoder().encode(line({ type: 'done', reason: 'interrupted' })))
        c.close()
      }
      return new Response(null, { status: 204 })
    }
    if (path.endsWith('/confirm'))
      return state.confirmStatus === 204
        ? new Response(null, { status: 204 })
        : json({ error: 'Confirmation inconnue ou expirée', code: 'CONFIRM_NOT_FOUND' }, state.confirmStatus)
    if (path.endsWith('/delete')) return new Response(null, { status: 204 })
    if (path === '/api/facts') return json({ facts: { redis: [{ entity: 'redis', attribute: 'version', value: '7', updated_at: 'x' }] } })
    if (path === '/api/profile/preferences') return json({ name: '', instructions: '', preferences: [String((body as { text: string }).text)] })
    if (path.endsWith('/answer'))
      return state.answerStatus === 204
        ? new Response(null, { status: 204 })
        : json({ error: 'Question inconnue ou expirée', code: 'QUESTION_NOT_FOUND' }, state.answerStatus)
    if (path === '/api/shares/TOK/revoke') return new Response(null, { status: 204 })
    if (path.endsWith('/revoke')) return json({ error: 'Lien de partage inconnu', code: 'SHARE_NOT_FOUND' }, 404)
    if (path.includes('/export?format=md')) return new Response('# Conversation S1\n\n## Vous\n\nbonjour', { status: 200 })
    if (path.endsWith('/share')) return json({ url: '/share/TOK', token: 'TOK', expires_at: '2026-11-05T10:00:00+00:00' }, 201)
    if (path.endsWith('/fork'))
      return state.forkFails ? json({ error: 'Point de bifurcation invalide', code: 'INVALID_REQUEST' }, 400) : json({ session_id: `S${++sessions}` }, 201)
    return json({ error: 'inconnu' }, 404)
  })
  return { calls, state, fetchFn: fetchFn as unknown as typeof fetch }
}

function engineWith(server: ReturnType<typeof fakeServer>, extra: Partial<ConstructorParameters<typeof HttpEngine>[0]> = {}) {
  const e = new HttpEngine({ token: 'JETON', baseUrl: 'http://api.test', fetchFn: server.fetchFn, ...extra })
  const got: EngineEvent[] = []
  e.subscribe((ev) => got.push(ev))
  return { e, got }
}

const doneCount = (got: EngineEvent[]) => got.filter((x) => x.type === 'done').length

test('un message crée la session puis rejoue le flux traduit', async () => {
  const server = fakeServer()
  const { e, got } = engineWith(server)
  e.send({ id: 'm1', text: 'salut' })
  await vi.waitFor(() => expect(doneCount(got)).toBe(1))
  expect(server.calls.map((c) => `${c.method} ${c.path}`)).toEqual([
    'POST /api/sessions',
    'POST /api/sessions/S1/messages',
  ])
  expect(server.calls[1].body).toEqual({ content: 'salut', skip_cache: false })
  expect(server.calls.every((c) => c.auth === 'Bearer JETON')).toBe(true)
  expect(got.map((x) => x.type)).toEqual(['turn_start', 'token', 'done'])
  expect(got[2]).toMatchObject({ turnId: 't1', interrupted: false })
})

test('la même session sert aux messages suivants', async () => {
  const server = fakeServer()
  const { e, got } = engineWith(server)
  e.send({ id: 'm1', text: 'un' })
  await vi.waitFor(() => expect(doneCount(got)).toBe(1))
  e.send({ id: 'm2', text: 'deux' })
  await vi.waitFor(() => expect(doneCount(got)).toBe(2))
  expect(server.calls.filter((c) => c.path === '/api/sessions')).toHaveLength(1)
})

test("un second message pendant un tour est refusé sans appeler le serveur", async () => {
  const server = fakeServer()
  server.state.hang = true
  const { e, got } = engineWith(server)
  e.send({ id: 'm1', text: 'un' })
  await vi.waitFor(() => expect(got.some((x) => x.type === 'token')).toBe(true))
  e.send({ id: 'm2', text: 'deux' })
  expect(got.at(-1)).toMatchObject({ type: 'error' })
  expect(server.calls.filter((c) => c.path.endsWith('/messages'))).toHaveLength(1)
})

test('une panne réseau devient un événement error suivi de done', async () => {
  const { e, got } = engineWith({ ...fakeServer(), fetchFn: (async () => { throw new Error('réseau coupé') }) as unknown as typeof fetch })
  e.send({ id: 'm1', text: 'salut' })
  await vi.waitFor(() => expect(doneCount(got)).toBe(1))
  expect(got.find((x) => x.type === 'error')).toMatchObject({ message: expect.stringContaining('réseau coupé') })
})

test('un jeton refusé prévient et redemande le jeton', async () => {
  const server = fakeServer()
  server.state.unauthorized = true
  const onUnauthorized = vi.fn()
  const { e, got } = engineWith(server, { onUnauthorized })
  e.send({ id: 'm1', text: 'salut' })
  await vi.waitFor(() => expect(doneCount(got)).toBe(1))
  expect(onUnauthorized).toHaveBeenCalled()
  expect(got.find((x) => x.type === 'error')).toMatchObject({ message: expect.stringContaining('Jeton refusé') })
})

test("un flux coupé avant done est signalé, et le tour se termine", async () => {
  const server = fakeServer()
  server.state.events = [{ type: 'token', text: 'à moi' }]
  const { e, got } = engineWith(server)
  e.send({ id: 'm1', text: 'salut' })
  await vi.waitFor(() => expect(doneCount(got)).toBe(1))
  expect(got.find((x) => x.type === 'error')).toMatchObject({ message: expect.stringContaining('fermé le flux') })
})

test("la saisie vide n'appelle pas le serveur", () => {
  const server = fakeServer()
  const { e } = engineWith(server)
  e.send({ id: 'm1', text: '  ' })
  expect(server.calls).toHaveLength(0)
})

test('confirmation : envoie confirm_id et approved, et signale une demande expirée', async () => {
  const server = fakeServer()
  server.state.hang = true
  server.state.events = [{ type: 'confirm_request', id: 'C1', confirm_id: 'C1', tool: 'write_file', risk: 'write', summary: 'diff', arguments: {}, timeout_s: 120 }]
  const { e, got } = engineWith(server)
  e.send({ id: 'm1', text: 'écris' })
  await vi.waitFor(() => expect(got.some((x) => x.type === 'confirm_request')).toBe(true))
  e.confirm('C1', true)
  await vi.waitFor(() => expect(server.calls.some((c) => c.path.endsWith('/confirm'))).toBe(true))
  expect(server.calls.find((c) => c.path.endsWith('/confirm'))).toMatchObject({
    path: '/api/sessions/S1/confirm',
    body: { confirm_id: 'C1', approved: true },
  })
  server.state.confirmStatus = 404
  e.confirm('C1', false)
  await vi.waitFor(() => expect(got.at(-1)).toMatchObject({ type: 'error', message: expect.stringContaining('expiré') }))
})

test('question (X4) : le formulaire arrive, la réponse part avec question_id et values', async () => {
  const server = fakeServer()
  server.state.hang = true
  server.state.events = [{
    type: 'question', question_id: 'Q1', title: 'Quel style ?', timeout_s: 100,
    fields: [{ id: 'style', kind: 'choice', label: 'Style', options: ['pytest', 'unittest'] }],
  }]
  const { e, got } = engineWith(server)
  e.send({ id: 'm1', text: 'écris des tests' })
  await vi.waitFor(() => expect(got.some((x) => x.type === 'question')).toBe(true))
  expect(got.find((x) => x.type === 'question')).toMatchObject({ requestId: 'Q1', title: 'Quel style ?' })
  e.answer('Q1', { style: 'pytest' })
  await vi.waitFor(() => expect(server.calls.some((c) => c.path.endsWith('/answer'))).toBe(true))
  expect(server.calls.find((c) => c.path.endsWith('/answer'))).toMatchObject({
    path: '/api/sessions/S1/answer',
    body: { question_id: 'Q1', values: { style: 'pytest' } },
  })
  server.state.answerStatus = 404
  e.answer('Q1', { style: 'pytest' })
  await vi.waitFor(() => expect(got.at(-1)).toMatchObject({ type: 'error', message: expect.stringContaining('expiré') }))
})

test("interrupt : le serveur termine le tour par done interrupted, sans doublon", async () => {
  const server = fakeServer()
  server.state.hang = true
  server.state.events = [{ type: 'token', text: 'long…' }]
  const { e, got } = engineWith(server)
  e.send({ id: 'm1', text: 'long' })
  await vi.waitFor(() => expect(got.some((x) => x.type === 'token')).toBe(true))
  e.interrupt()
  await vi.waitFor(() => expect(doneCount(got)).toBe(1))
  expect(got.at(-1)).toMatchObject({ type: 'done', interrupted: true })
  expect(server.calls.some((c) => c.path === '/api/sessions/S1/interrupt')).toBe(true)
})

test("interrupt : si le serveur ne répond pas, l'interface coupe le flux elle-même", async () => {
  const server = fakeServer()
  server.state.hang = true
  server.state.events = [{ type: 'token', text: 'long…' }]
  const { e, got } = engineWith(server, { interruptGraceMs: 20 })
  e.send({ id: 'm1', text: 'long' })
  await vi.waitFor(() => expect(got.some((x) => x.type === 'token')).toBe(true))
  server.state.streamController = null // le serveur ignore l'interruption
  e.interrupt()
  await vi.waitFor(() => expect(doneCount(got)).toBe(1))
  expect(got.at(-1)).toMatchObject({ type: 'done', interrupted: true })
})

test('interrupt sans tour en cours ne fait rien', () => {
  const server = fakeServer()
  const { e, got } = engineWith(server)
  e.interrupt()
  expect(got).toEqual([])
  expect(server.calls).toEqual([])
})

test("modifier un message crée une branche à partir de l'historique enregistré", async () => {
  const server = fakeServer()
  const { e, got } = engineWith(server)
  e.send({ id: 'm1', text: 'un' })
  await vi.waitFor(() => expect(doneCount(got)).toBe(1))
  e.send({ id: 'm2', text: 'deux' })
  await vi.waitFor(() => expect(doneCount(got)).toBe(2))
  expect(e.editMessage('m2', 'deux bis')).toBe('b1')
  await vi.waitFor(() => expect(doneCount(got)).toBe(3))
  const fork = server.calls.find((c) => c.path.endsWith('/fork'))
  expect(fork).toMatchObject({ path: '/api/sessions/S1/fork', body: { at_message: 2 } })
  expect(server.calls.at(-1)).toMatchObject({ path: '/api/sessions/S2/messages', body: { content: 'deux bis', skip_cache: false } })
  // Revenir sur la branche principale : les messages repartent dans la session d'origine.
  e.selectBranch('main')
  e.send({ id: 'm3', text: 'trois' })
  await vi.waitFor(() => expect(doneCount(got)).toBe(4))
  expect(server.calls.at(-1)?.path).toBe('/api/sessions/S1/messages')
})

test('une bifurcation refusée est annoncée, et la branche repart vide', async () => {
  const server = fakeServer()
  server.state.forkFails = true
  const { e, got } = engineWith(server)
  e.send({ id: 'm1', text: 'un' })
  await vi.waitFor(() => expect(doneCount(got)).toBe(1))
  e.editMessage('m1', 'un bis')
  await vi.waitFor(() => expect(doneCount(got)).toBe(2))
  expect(got.filter((x) => x.type === 'error').map((x) => (x as { message: string }).message).join(' ')).toContain('conversation vide')
})

test('modifier un message inconnu est une erreur explicite', () => {
  const { e, got } = engineWith(fakeServer())
  expect(e.editMessage('inconnu', 'x')).toBeNull()
  expect(got[0]).toMatchObject({ type: 'error' })
})

test("/again redemande la dernière question au modèle, sans le cache", async () => {
  const server = fakeServer()
  const { e, got } = engineWith(server)
  e.send({ id: 'm0', text: '/again' })
  expect(got.at(-1)).toMatchObject({ type: 'error', message: expect.stringContaining('Aucune question') })
  e.send({ id: 'm1', text: 'Comment lancer les tests ?' })
  await vi.waitFor(() => expect(doneCount(got)).toBe(1))
  e.send({ id: 'm2', text: '/again' })
  await vi.waitFor(() => expect(doneCount(got)).toBe(2))
  expect(server.calls.at(-1)?.body).toEqual({ content: 'Comment lancer les tests ?', skip_cache: true })
})

test('un message refusé par le serveur affiche son erreur', async () => {
  const server = fakeServer()
  const real = server.fetchFn
  server.fetchFn = (async (url: string, init?: RequestInit) =>
    url.endsWith('/messages')
      ? new Response(JSON.stringify({ error: 'Un tour est déjà en cours', code: 'TURN_IN_PROGRESS', details: '' }), { status: 409 })
      : real(url, init)) as unknown as typeof fetch
  const { e, got } = engineWith(server)
  e.send({ id: 'm1', text: 'salut' })
  await vi.waitFor(() => expect(doneCount(got)).toBe(1))
  expect(got.find((x) => x.type === 'error')).toMatchObject({ message: 'Un tour est déjà en cours' })
})

test('A5 (ADR-0054) : changer de persona passe par la route de la conversation', async () => {
  const server = fakeServer()
  const { e } = engineWith(server)
  e.switchPersona('reviewer')
  await vi.waitFor(() =>
    expect(server.calls.find((c) => c.path.endsWith('/persona'))).toMatchObject({ method: 'POST', body: { persona: 'reviewer' } }),
  )
})

test("#44 : liste les conversations passées, en rouvre une et la continue", async () => {
  const server = fakeServer()
  const { e } = engineWith(server)
  expect(await e.listSessions()).toEqual([{ id: 'OLD', title: 'Hier', updatedAt: '2026-10-28T18:00:00+00:00', messageCount: 4 }])
  const history = await e.openSession('OLD')
  expect(history?.map((m) => [m.role, m.text])).toEqual([['user', 'q1'], ['assistant', 'r1'], ['user', 'q2'], ['assistant', 'r2']])
  // ↻ sur une conversation rouverte : la dernière question connue est redemandée.
  e.send({ id: 'm8', text: '/again' })
  await vi.waitFor(() => expect(server.calls.some((c) => c.path.endsWith('/messages'))).toBe(true))
  expect(server.calls.find((c) => c.path.endsWith('/messages'))?.body).toEqual({ content: 'q2', skip_cache: true })
  server.calls.length = 0
  e.send({ id: 'm9', text: 'suite' })
  await vi.waitFor(() => expect(server.calls.some((c) => c.path.endsWith('/messages'))).toBe(true))
  // Aucune nouvelle session : la suite part dans la conversation rouverte.
  expect(server.calls.filter((c) => c.method === 'POST' && c.path === '/api/sessions')).toHaveLength(0)
  expect(server.calls.find((c) => c.path.endsWith('/messages'))?.path).toBe('/api/sessions/OLD/messages')
})

test("#44 : modifier un message d'une conversation rouverte bifurque au bon endroit", async () => {
  const server = fakeServer()
  const { e } = engineWith(server)
  const history = await e.openSession('OLD')
  const second = history!.filter((m) => m.role === 'user')[1]
  e.editMessage(second.id, 'q2 bis')
  await vi.waitFor(() => expect(server.calls.some((c) => c.path.endsWith('/fork'))).toBe(true))
  expect(server.calls.find((c) => c.path.endsWith('/fork'))).toMatchObject({ path: '/api/sessions/OLD/fork', body: { at_message: 2 } })
})

test('nouvelle conversation et suppression de la conversation ouverte : les messages suivants créent une session neuve', async () => {
  const server = fakeServer()
  const { e } = engineWith(server)
  await e.openSession('OLD')
  expect(e.currentSession()).toBe('OLD')
  expect(await e.deleteSession('OLD')).toBe(true)
  expect(server.calls.at(-1)).toMatchObject({ method: 'POST', path: '/api/sessions/OLD/delete' })
  expect(e.currentSession()).toBeNull()
  e.send({ id: 'm1', text: 'bonjour' })
  await vi.waitFor(() => expect(server.calls.some((c) => c.path.endsWith('/messages'))).toBe(true))
  expect(server.calls.find((c) => c.path.endsWith('/messages'))?.path).toBe('/api/sessions/S1/messages')
  expect(e.newConversation()).toBe(true)
  expect(e.currentSession()).toBeNull()
})

test('partage (X3) : publie la session de la branche affichée et rend une URL complète', async () => {
  const server = fakeServer()
  const { e } = engineWith(server)
  expect(await e.share()).toBeNull() // aucune session encore
  e.send({ id: 'm1', text: 'bonjour' })
  await vi.waitFor(() => expect(server.calls.some((c) => c.path.endsWith('/messages'))).toBe(true))
  expect(await e.share()).toEqual({ url: 'http://api.test/share/TOK', token: 'TOK', expiresAt: '2026-11-05T10:00:00+00:00' })
  expect(server.calls.at(-1)).toMatchObject({ method: 'POST', path: '/api/sessions/S1/share' })
})

test('partage (X3) : un lien se révoque, un jeton inconnu est signalé', async () => {
  const server = fakeServer()
  const { e, got } = engineWith(server)
  expect(await e.revokeShare('TOK')).toBe(true)
  expect(server.calls.at(-1)).toMatchObject({ method: 'POST', path: '/api/shares/TOK/revoke' })
  expect(await e.revokeShare('AUTRE')).toBe(false)
  expect(got.at(-1)).toEqual({ type: 'error', message: 'Lien de partage inconnu' })
})

test('export (X3) : le serveur exporte la conversation affichée, secrets masqués de son côté', async () => {
  const server = fakeServer()
  const { e } = engineWith(server)
  expect(await e.exportSession('md')).toBeNull() // aucune session encore
  e.send({ id: 'm1', text: 'bonjour' })
  await vi.waitFor(() => expect(server.calls.some((c) => c.path.endsWith('/messages'))).toBe(true))
  expect(await e.exportSession('md')).toContain('## Vous')
  expect(server.calls.at(-1)).toMatchObject({ method: 'GET', path: '/api/sessions/S1/export?format=md' })
})

test('profil et faits (M1, M3) : les faits du serveur sont mis à plat, la préférence part en POST', async () => {
  const server = fakeServer()
  const { e } = engineWith(server)
  expect(await e.getFacts()).toEqual([{ entity: 'redis', attribute: 'version', value: '7' }])
  expect((await e.addPreference('utilise pytest'))?.preferences).toEqual(['utilise pytest'])
  expect(server.calls.at(-1)).toMatchObject({ method: 'POST', path: '/api/profile/preferences', body: { text: 'utilise pytest' } })
})

test("le tour ne se termine qu'à la fermeture du flux : le serveur enregistre la conversation entre `done` et la fin", async () => {
  const server = fakeServer()
  server.state.hang = true
  const { e, got } = engineWith(server)
  e.send({ id: 'm1', text: 'bonjour' })
  await vi.waitFor(() => expect(got.some((x) => x.type === 'token')).toBe(true))
  await new Promise((r) => setTimeout(r, 20))
  expect(doneCount(got)).toBe(0) // `done` reçu, flux encore ouvert : la session est encore occupée
  server.state.streamController?.close()
  await vi.waitFor(() => expect(doneCount(got)).toBe(1))
})

test('EV4 et EV3 : corpus adversarial, 409 signalé, journal et métriques traduits du serveur', async () => {
  const urls: string[] = []
  const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status })
  const fetchFn = (async (url: string, init?: RequestInit) => {
    urls.push(`${init?.method ?? 'GET'} ${url}`)
    if (url.endsWith('/api/quality/adversarial/run'))
      return json({ error: 'Les attaques sont déjà en cours', code: 'ALREADY_RUNNING', details: '' }, 409)
    if (url.endsWith('/api/quality/adversarial'))
      return json({ cases: [{ id: 'EV4-INJ-01', category: 'INJ', attempt: 'a', expected: 'SIGNALÉ', observed: 'SIGNALÉ', verdict: 'OK', detail: '' }],
        summary: { total: 1, ok: 1, known_gaps: 0, regressions: 0, fixed: 0, skipped: 0 }, ran_at: null, source: 'committed' })
    if (url.includes('/api/journal/metrics'))
      return json({ days: 7, tools: [{ tool: 'read_file', calls: 2, failures: 0, mean_ms: 10, max_ms: 15 }], model: { turns: 1, mean_ms: 900, max_ms: 900, not_final: 0 } })
    if (url.includes('/api/journal'))
      return json({ session_id: 's1', turns: [{ id: 3, started_at: 't', model_ms: 900, tokens_sent: 12, outcome: 'final_answer', interface: 'cli',
        tools: [{ tool: 'read_file', arguments: '{}', duration_ms: 10, ok: true, agent: 'main' }] }] })
    return json({}, 404)
  }) as unknown as typeof fetch
  const e = new HttpEngine({ token: 'JETON', baseUrl: 'http://api.test', fetchFn })
  const got: EngineEvent[] = []
  e.subscribe((ev) => got.push(ev))

  const run = await e.adversarialResults()
  expect(run).toMatchObject({ source: 'committed', ranAt: null, summary: { total: 1, ok: 1, knownGaps: 0 } })
  expect(run?.cases[0]).toMatchObject({ id: 'EV4-INJ-01', verdict: 'OK' })
  expect(await e.runAdversarial()).toBeNull()
  expect(got.find((x) => x.type === 'error')).toMatchObject({ message: 'Les attaques sont déjà en cours' })

  const turns = await e.journal('s1')
  expect(turns?.[0]).toMatchObject({ id: 3, modelMs: 900, tokensSent: 12, interface: 'cli', tools: [{ tool: 'read_file', durationMs: 10, ok: true, agent: 'main' }] })
  expect(urls).toContain('GET http://api.test/api/journal?session=s1&limit=100')
  expect(await e.journalMetrics(7)).toMatchObject({ tools: [{ tool: 'read_file', meanMs: 10, maxMs: 15 }], model: { turns: 1, meanMs: 900 } })
})
