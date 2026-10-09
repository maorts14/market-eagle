import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { agent, exampleQuestion, followUpQuestion } from './agent'

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
    expect(completed.trusted_result?.data).toMatchObject({ source: 'synthetic-v1', synthetic: true, return_rankings_trusted: false })
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
