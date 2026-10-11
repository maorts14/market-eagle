import expected from './agent-expected.json'
import { getFixtureExplorer } from './explorer'

export const agentMode = import.meta.env.VITE_AGENT_MODE === 'api' ? 'api' : 'fixture'
export const exampleQuestion = 'Which stock gained most while daily dollar trading volume exceeded $100,000 on at least 80% of observed days last month?'
export const followUpQuestion = 'How many observed days qualified for EPSI?'

export type TurnStatus = 'running' | 'cancel_requested' | 'completed' | 'needs_clarification' | 'unsupported' | 'failed' | 'cancelled'
export type AgentSortMeasure = 'period_return' | 'excess_vs_sector' | 'breadth' | 'sector_return' | 'qualifying_fraction' | 'qualifying_days'
export type AgentRow = {
  ticker?: string
  name?: string
  sector_code?: string
  period_return?: number | null
  excess_vs_sector?: number | string | null
  qualifying_fraction?: number | string | null
  breadth?: number | null
  sector_return?: number | null
  qualifying_days?: number | null
  observed_usable_days?: number
  requested_sessions?: number
  requested_coverage?: number | null
  dollar_volume_inputs?: string[]
  dollar_volume_formulas?: { input: string; formula: string; estimated: boolean }[]
}
export type TrustedResult = {
  request_version: number
  metric_version: string
  requested_window: { start: string; end: string }
  resolved_window: { comparison_session: string | null; first_session: string; last_session: string }
  catalog: { snapshot_id: string; as_of: string; tracked_count: number; scope?: 'private_five_stock_sample' }
  data: { source: string; feed: string; price_basis: string; as_of: string | null; as_of_kind: 'provider' | 'fetched' | 'mixed' | null; provisional: boolean; synthetic: boolean; return_rankings_trusted: boolean }
  market: { eligible_count: number; excluded_count: number; return: number | null }
  eligible_count: number
  matched_count: number
  exclusions: { ticker?: string; stock_id?: string; reason: string }[]
  rows: AgentRow[]
  calculated_at: string
  ranking_scope: string
  coverage_label: string
}
export type AgentTurn = {
  turn_id: string
  conversation_id: string
  question: string
  status: TurnStatus
  decision: { kind: 'query' | 'clarification' | 'unsupported'; assumptions: string[]; message?: string; request?: { sort: { measure: AgentSortMeasure } } | null } | null
  trusted_result: TrustedResult | null
  evidence_id: string | null
  agent_explanation: string | null
  error: string | null
}
export type AgentConversation = { conversation_id: string; active_turn_id: string | null; turns: AgentTurn[] }
export type AgentConversationSummary = { conversation_id: string; title: string; active_turn_id: string | null; updated_at: string }

export class AgentApiError extends Error {
  readonly status: number
  constructor(message: string, status: number) { super(message); this.status = status }
}

async function request<T>(path: string, method = 'GET', body?: object): Promise<T> {
  let response: Response
  try {
    response = await fetch(`/api/v1/agent${path}`, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    })
  } catch {
    throw new AgentApiError('Cannot reach the research agent service. Check the connection and retry.', 0)
  }
  let payload: { detail?: string }
  try {
    payload = await response.json()
  } catch {
    throw new AgentApiError('The research agent service returned an unreadable response. Check its configuration and retry.', response.status)
  }
  if (!response.ok) {
    const message = typeof payload.detail === 'string' ? payload.detail : `Agent request failed (${response.status}).`
    throw new AgentApiError(message, response.status)
  }
  return payload as T
}

type FixtureTurn = AgentTurn & { request_id: string; ready_at: number }
type FixtureConversation = { turns: FixtureTurn[]; updated_at?: string }
type FixtureStore = Record<string, FixtureConversation>
const fixtureKey = 'market-eagle-agent-fixture-v1'

function readFixture(): FixtureStore {
  return JSON.parse(localStorage.getItem(fixtureKey) ?? '{}') as FixtureStore
}

function saveFixture(store: FixtureStore) {
  localStorage.setItem(fixtureKey, JSON.stringify(store))
}

async function completeFixture(turn: FixtureTurn): Promise<void> {
  const previous = expected.gain_plus_volume_last_month_as_of_2026_01_08
  const isExample = turn.question === exampleQuestion || turn.question === followUpQuestion
  if (!isExample) {
    turn.status = 'unsupported'
    turn.decision = { kind: 'unsupported', assumptions: [], message: 'The fixture has no answer for this question.' }
    turn.agent_explanation = 'This local fixture replays only the documented example and its follow-up. Use API mode for free-text research.'
    return
  }

  const explorer = await getFixtureExplorer({ start: previous.requested_start, end: previous.requested_end })
  const winner = previous.winner
  turn.status = 'completed'
  turn.decision = {
    kind: 'query',
    assumptions: ['In this fixed fixture, “last month” means December 2025.', 'The frequency denominator is observed usable days.'],
  }
  turn.evidence_id = `fixture-${turn.turn_id}`
  turn.trusted_result = {
    request_version: 1,
    metric_version: 'return-v1',
    requested_window: explorer.requested_window,
    resolved_window: explorer.resolved_window,
    catalog: explorer.catalog,
    data: { ...explorer.data, return_rankings_trusted: false },
    market: explorer.market,
    eligible_count: explorer.market.eligible_count,
    matched_count: previous.qualifying_ranked_candidates.length,
    exclusions: previous.exclusions,
    rows: [{
      ticker: winner.ticker,
      name: 'Epsilon Fiction',
      sector_code: 'IND',
      period_return: winner.return,
      qualifying_fraction: winner.qualifying_days / winner.observed_usable_days,
      qualifying_days: winner.qualifying_days,
      observed_usable_days: winner.observed_usable_days,
      requested_sessions: winner.requested_sessions,
      requested_coverage: 1,
      dollar_volume_inputs: winner.dollar_volume_inputs,
      dollar_volume_formulas: [{ input: 'reported_notional', formula: 'provider reported traded notional', estimated: false }],
    }],
    calculated_at: new Date().toISOString(),
    ranking_scope: 'eligible_stocks_only',
    coverage_label: `Evaluated ${explorer.market.eligible_count} of ${explorer.catalog.tracked_count} tracked stocks`,
  }
  turn.agent_explanation = turn.question === followUpQuestion
    ? 'EPSI qualified on all 23 observed usable days in the fictional December 2025 history.'
    : 'EPSI led the qualifying stocks in the fictional December 2025 history. This is a deterministic interface fixture, not a live agent answer.'
}

async function settleFixture(store: FixtureStore, turn: FixtureTurn): Promise<void> {
  if (Date.now() < turn.ready_at) return
  if (turn.status === 'cancel_requested') turn.status = 'cancelled'
  else if (turn.status === 'running') await completeFixture(turn)
  else return
  store[turn.conversation_id].updated_at = new Date().toISOString()
  saveFixture(store)
}

function findFixtureTurn(store: FixtureStore, turnId: string): FixtureTurn {
  for (const conversation of Object.values(store)) {
    const turn = conversation.turns.find((item) => item.turn_id === turnId)
    if (turn) return turn
  }
  throw new AgentApiError('Turn not found.', 404)
}

export function createAgentAdapter(mode: 'api' | 'fixture') {
  return {
  async listConversations(): Promise<AgentConversationSummary[]> {
    if (mode === 'api') {
      const response = await request<{ conversations: AgentConversationSummary[] }>('/conversations')
      return response.conversations
    }
    const store = readFixture()
    const conversations = Object.entries(store).map(([conversation_id, conversation]) => ({
      conversation_id,
      title: conversation.turns[0]?.question.slice(0, 48) ?? 'New conversation',
      active_turn_id: conversation.turns.find((turn) => turn.status === 'running' || turn.status === 'cancel_requested')?.turn_id ?? null,
      updated_at: conversation.updated_at ?? new Date(0).toISOString(),
    }))
    return conversations.sort((a, b) => b.updated_at.localeCompare(a.updated_at))
  },

  async createConversation(): Promise<string> {
    if (mode === 'api') {
      const response = await request<{ conversation_id: string }>('/conversations', 'POST')
      return response.conversation_id
    }
    const id = crypto.randomUUID()
    const store = readFixture()
    store[id] = { turns: [], updated_at: new Date().toISOString() }
    saveFixture(store)
    return id
  },

  async getConversation(id: string): Promise<AgentConversation> {
    if (mode === 'api') return request<AgentConversation>(`/conversations/${encodeURIComponent(id)}`)
    const store = readFixture()
    const conversation = store[id]
    if (!conversation) throw new AgentApiError('Conversation not found.', 404)
    const active = conversation.turns.find((turn) => turn.status === 'running' || turn.status === 'cancel_requested')
    if (active) await settleFixture(store, active)
    return {
      conversation_id: id,
      active_turn_id: active && (active.status === 'running' || active.status === 'cancel_requested') ? active.turn_id : null,
      turns: conversation.turns,
    }
  },

  async submitTurn(id: string, question: string, requestId: string): Promise<AgentTurn> {
    if (mode === 'api') return request<AgentTurn>(`/conversations/${encodeURIComponent(id)}/turns`, 'POST', { request_id: requestId, question })
    const store = readFixture()
    const conversation = store[id]
    if (!conversation) throw new AgentApiError('Conversation not found.', 404)
    const duplicate = conversation.turns.find((turn) => turn.request_id === requestId)
    if (duplicate) return duplicate
    if (conversation.turns.some((turn) => turn.status === 'running' || turn.status === 'cancel_requested')) {
      throw new AgentApiError('Conversation has an active turn.', 409)
    }
    const turn: FixtureTurn = {
      turn_id: crypto.randomUUID(), conversation_id: id, request_id: requestId, question,
      status: 'running', ready_at: Date.now() + 2200, decision: null, trusted_result: null,
      evidence_id: null, agent_explanation: null, error: null,
    }
    conversation.turns.push(turn)
    conversation.updated_at = new Date().toISOString()
    saveFixture(store)
    return turn
  },

  async getTurn(id: string): Promise<AgentTurn> {
    if (mode === 'api') return request<AgentTurn>(`/turns/${encodeURIComponent(id)}`)
    const store = readFixture()
    const turn = findFixtureTurn(store, id)
    await settleFixture(store, turn)
    return turn
  },

  async cancelTurn(id: string): Promise<AgentTurn> {
    if (mode === 'api') return request<AgentTurn>(`/turns/${encodeURIComponent(id)}/cancel`, 'POST')
    const store = readFixture()
    const turn = findFixtureTurn(store, id)
    if (turn.status === 'running') {
      turn.status = 'cancel_requested'
      turn.ready_at = Date.now() + 400
      store[turn.conversation_id].updated_at = new Date().toISOString()
      saveFixture(store)
    }
    return turn
  },

  async deleteConversation(id: string): Promise<void> {
    if (mode === 'api') {
      await request<{ deleted: true }>(`/conversations/${encodeURIComponent(id)}`, 'DELETE')
      return
    }
    const store = readFixture()
    if (!store[id]) throw new AgentApiError('Conversation not found.', 404)
    delete store[id]
    saveFixture(store)
  },
  }
}

export const agent = createAgentAdapter(agentMode)
