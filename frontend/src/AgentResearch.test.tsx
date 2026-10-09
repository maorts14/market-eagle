import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { TurnCard } from './AgentResearch'
import type { AgentTurn, TrustedResult } from './lib/agent'

describe('research result rendering', () => {
  it('shows frequency as the lead metric without inventing a comparison close or sector return', () => {
    const result: TrustedResult = {
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
    const turn: AgentTurn = {
      turn_id: 'turn-1', conversation_id: 'conversation-1', question: 'How often did DELT qualify?',
      status: 'completed', decision: null, trusted_result: result, evidence_id: 'evidence-1',
      agent_explanation: null, error: null,
    }

    const html = renderToStaticMarkup(<TurnCard turn={turn} />)

    expect(html).toContain('Qualifying days</span><strong>60.0%')
    expect(html).toContain('3 of 5 observed usable days qualified')
    expect(html).toContain('Comparison close</dt><dd>None required for frequency-only result')
    expect(html).not.toContain('Sector return')
    expect(html).not.toContain('Invalid Date')
    expect(html).not.toContain('Return rankings remain untrusted')
  })
})
