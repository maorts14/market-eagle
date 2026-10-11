import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { TurnCard } from './AgentResearch'
import type { AgentTurn, TrustedResult } from './lib/agent'

function frequencyResult(): TrustedResult {
  return {
      request_version: 1,
      metric_version: 'frequency-v1',
      requested_window: { start: '2023-12-29', end: '2023-12-29' },
      resolved_window: { comparison_session: null, first_session: '2023-12-29', last_session: '2023-12-29' },
      catalog: { snapshot_id: 'catalog-1', as_of: '2023-12-29', tracked_count: 5 },
      data: { source: 'test', feed: 'daily', price_basis: 'unadjusted', as_of: null, as_of_kind: null, provisional: false, synthetic: false, return_rankings_trusted: false },
      market: { eligible_count: 4, excluded_count: 1, return: null },
      eligible_count: 4,
      matched_count: 1,
      exclusions: [],
      rows: [{ ticker: 'DELT', name: 'Delta', period_return: null, qualifying_fraction: '0.6', qualifying_days: 3, observed_usable_days: 5 }],
      calculated_at: '2023-12-29T20:00:00Z',
      ranking_scope: 'eligible_stocks_only',
      coverage_label: 'Evaluated 4 of 5 tracked stocks',
  }
}

describe('research result rendering', () => {
  it('shows frequency as the lead metric without inventing a comparison close or sector return', () => {
    const result = frequencyResult()
    const turn: AgentTurn = {
      turn_id: 'turn-1', conversation_id: 'conversation-1', question: 'How often did DELT qualify?',
      status: 'completed', decision: null, trusted_result: result, evidence_id: 'evidence-1',
      agent_explanation: null, error: null,
    }

    const html = renderToStaticMarkup(<TurnCard turn={turn} />)

    expect(html).toContain('Qualifying share</span><strong>60.0%')
    expect(html).toContain('3 of 5 observed usable days qualified')
    expect(html).toContain('Comparison close</dt><dd>None required for frequency-only result')
    expect(html).not.toContain('Sector return')
    expect(html).not.toContain('Invalid Date')
    expect(html).not.toContain('Return rankings remain untrusted')
  })

  it('shows every returned rank and the selected measure even when rows also include returns', () => {
    const result = frequencyResult()
    result.matched_count = 3
    result.rows = [
      { ticker: 'DELT', name: 'Delta', period_return: 0.42, qualifying_fraction: '0.8', qualifying_days: 4, observed_usable_days: 5 },
      { ticker: 'EPSI', name: 'Epsilon', period_return: 0.91, qualifying_fraction: '0.6', qualifying_days: 3, observed_usable_days: 5 },
    ]
    const turn: AgentTurn = {
      turn_id: 'turn-2', conversation_id: 'conversation-1', question: 'Which stocks qualify most often?',
      status: 'completed', decision: { kind: 'query', assumptions: [], request: { sort: { measure: 'qualifying_fraction' } } },
      trusted_result: result, evidence_id: 'evidence-2', agent_explanation: null, error: null,
    }

    const html = renderToStaticMarkup(<TurnCard turn={turn} />)

    expect(html).toContain('aria-label="Verified ranked results"')
    expect(html).toContain('Qualifying share</th>')
    expect(html).toContain('DELT</strong><span>Delta</span>')
    expect(html).toContain('EPSI</strong><span>Epsilon</span>')
    expect(html).toContain('80.0%</strong>')
    expect(html).toContain('60.0%</strong>')
    expect(html).toContain('Showing 2 of 3 matches.')
    expect(html).not.toContain('42.0%</strong>')
    expect(html).not.toContain('91.0%</strong>')
  })

  it('uses the requested excess-return measure for a single result', () => {
    const result = frequencyResult()
    result.rows = [{ ticker: 'DELT', period_return: 0.42, excess_vs_sector: -0.03 }]
    const turn: AgentTurn = {
      turn_id: 'turn-3', conversation_id: 'conversation-1', question: 'How far below its sector was DELT?',
      status: 'completed', decision: { kind: 'query', assumptions: [], request: { sort: { measure: 'excess_vs_sector' } } },
      trusted_result: result, evidence_id: 'evidence-3', agent_explanation: null, error: null,
    }

    const html = renderToStaticMarkup(<TurnCard turn={turn} />)

    expect(html).toContain('Excess vs sector</span><strong>-3.0 pp')
    expect(html).not.toContain('Period return</span><strong>+42.0%')
  })
})
