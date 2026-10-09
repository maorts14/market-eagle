import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { agent, createAgentAdapter, exampleQuestion, followUpQuestion } from './agent'

const fixturePath = resolve(import.meta.dirname, '../../public/fixtures')
const storage = new Map<string, string>()

beforeEach(() => {
  storage.clear()
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => { storage.set(key, value) },
  })
  vi.stubGlobal('fetch', async (url: string) => ({
    text: async () => readFileSync(resolve(fixturePath, String(url).split('/').at(-1)!), 'utf8'),
  }))
})

afterEach(() => { vi.restoreAllMocks() })

describe('local agent fixture', () => {
  it('lists conversations for a new adapter and reflects titles, active turns, and deletion', async () => {
    const first = await agent.createConversation()
    const second = await agent.createConversation()
    const started = await agent.submitTurn(first, exampleQuestion, 'first-request')
    const anotherView = createAgentAdapter('fixture')

    expect(await anotherView.listConversations()).toEqual(expect.arrayContaining([
      expect.objectContaining({ conversation_id: first, title: exampleQuestion.slice(0, 48), active_turn_id: started.turn_id }),
      expect.objectContaining({ conversation_id: second, title: 'New conversation', active_turn_id: null }),
    ]))
    await anotherView.deleteConversation(first)
    expect((await agent.listConversations()).map((item) => item.conversation_id)).toEqual([second])
  })

  it('keeps a stable request ID and returns sourced synthetic facts for a follow-up', async () => {
    const conversationId = await agent.createConversation()
    const started = await agent.submitTurn(conversationId, exampleQuestion, 'request-1')
    expect(started.status).toBe('running')
    expect((await agent.submitTurn(conversationId, exampleQuestion, 'request-1')).turn_id).toBe(started.turn_id)
    await expect(agent.submitTurn(conversationId, followUpQuestion, 'request-2')).rejects.toMatchObject({ status: 409 })

    vi.spyOn(Date, 'now').mockReturnValue(Date.now() + 3000)
    const completed = await agent.getTurn(started.turn_id)
    expect(completed.status).toBe('completed')
    expect(completed.trusted_result?.rows[0]).toMatchObject({ ticker: 'EPSI', qualifying_days: 23, observed_usable_days: 23 })
    expect(completed.trusted_result?.data).toMatchObject({ source: 'synthetic-v1', as_of_kind: 'provider', synthetic: true, return_rankings_trusted: false })
    expect(completed.trusted_result?.coverage_label).toBe('Evaluated 4 of 5 tracked stocks')

    const followUp = await agent.submitTurn(conversationId, followUpQuestion, 'request-2')
    vi.spyOn(Date, 'now').mockReturnValue(Date.now() + 3000)
    expect((await agent.getTurn(followUp.turn_id)).status).toBe('completed')
    expect((await agent.getConversation(conversationId)).turns).toHaveLength(2)
  })

  it('cancels a turn before answering and permits a new turn', async () => {
    const conversationId = await agent.createConversation()
    const started = await agent.submitTurn(conversationId, exampleQuestion, 'cancel-me')
    expect((await agent.cancelTurn(started.turn_id)).status).toBe('cancel_requested')
    vi.spyOn(Date, 'now').mockReturnValue(Date.now() + 500)
    expect((await agent.getTurn(started.turn_id)).status).toBe('cancelled')
    expect((await agent.submitTurn(conversationId, 'Why did EPSI rise?', 'next')).status).toBe('running')
    await agent.deleteConversation(conversationId)
    await expect(agent.getConversation(conversationId)).rejects.toMatchObject({ status: 404 })
  })

  it('labels questions outside the fixture as unsupported', async () => {
    const conversationId = await agent.createConversation()
    const turn = await agent.submitTurn(conversationId, 'Why did EPSI rise?', 'unsupported')
    vi.spyOn(Date, 'now').mockReturnValue(Date.now() + 3000)
    const result = await agent.getTurn(turn.turn_id)
    expect(result.status).toBe('unsupported')
    expect(result.trusted_result).toBeNull()
    expect(result.agent_explanation).toContain('local fixture')
  })
})

describe('agent HTTP adapter', () => {
  it('uses the documented routes, request ID, and turn statuses', async () => {
    const turn = { turn_id: 'turn-1', conversation_id: 'conversation-1', question: 'Question', status: 'running', decision: null, trusted_result: null, evidence_id: null, agent_explanation: null, error: null }
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ conversation_id: 'conversation-1' }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ conversations: [{ conversation_id: 'conversation-1', title: 'Question', active_turn_id: null, updated_at: '2026-10-09T00:00:00Z' }] }) })
      .mockResolvedValueOnce({ ok: true, json: async () => turn })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ ...turn, status: 'cancel_requested' }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ ...turn, status: 'cancelled' }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ conversation_id: 'conversation-1', active_turn_id: null, turns: [{ ...turn, status: 'cancelled' }] }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ deleted: true }) })
    vi.stubGlobal('fetch', fetchMock)
    const api = createAgentAdapter('api')

    expect(await api.createConversation()).toBe('conversation-1')
    expect(await api.listConversations()).toEqual([{ conversation_id: 'conversation-1', title: 'Question', active_turn_id: null, updated_at: '2026-10-09T00:00:00Z' }])
    expect((await api.submitTurn('conversation-1', 'Question', 'stable-id')).status).toBe('running')
    expect((await api.cancelTurn('turn-1')).status).toBe('cancel_requested')
    expect((await api.getTurn('turn-1')).status).toBe('cancelled')
    expect((await api.getConversation('conversation-1')).turns).toHaveLength(1)
    await api.deleteConversation('conversation-1')

    expect(fetchMock.mock.calls.map(([url, options]) => [url, options.method])).toEqual([
      ['/api/v1/agent/conversations', 'POST'],
      ['/api/v1/agent/conversations', 'GET'],
      ['/api/v1/agent/conversations/conversation-1/turns', 'POST'],
      ['/api/v1/agent/turns/turn-1/cancel', 'POST'],
      ['/api/v1/agent/turns/turn-1', 'GET'],
      ['/api/v1/agent/conversations/conversation-1', 'GET'],
      ['/api/v1/agent/conversations/conversation-1', 'DELETE'],
    ])
    expect(JSON.parse(fetchMock.mock.calls[2][1].body)).toEqual({ request_id: 'stable-id', question: 'Question' })
  })

  it('exposes FastAPI busy and connection errors to the UI', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 409, json: async () => ({ detail: 'Conversation has an active turn' }) })
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({ detail: 'Could not reconnect agent turn' }) })
    vi.stubGlobal('fetch', fetchMock)
    const api = createAgentAdapter('api')
    await expect(api.submitTurn('conversation-1', 'Question', 'stable-id')).rejects.toMatchObject({ status: 409, message: 'Conversation has an active turn' })
    await expect(api.getTurn('turn-1')).rejects.toMatchObject({ status: 503, message: 'Could not reconnect agent turn' })
  })

  it('reports an unavailable or misconfigured service clearly', async () => {
    const api = createAgentAdapter('api')
    vi.stubGlobal('fetch', vi.fn().mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockResolvedValueOnce({ status: 502, json: async () => { throw new SyntaxError('HTML response') } }))
    await expect(api.createConversation()).rejects.toMatchObject({ status: 0, message: 'Cannot reach the research agent service. Check the connection and retry.' })
    await expect(api.createConversation()).rejects.toMatchObject({ status: 502, message: 'The research agent service returned an unreadable response. Check its configuration and retry.' })
  })
})
