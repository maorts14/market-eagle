import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { SectorTable, StockTable } from './App'
import type { ExplorerSector } from './lib/explorer'

const sampleGroup: ExplorerSector = {
  sector_code: 'UNCLASSIFIED',
  sector_name: 'Unclassified private sample',
  tracked_count: 5,
  eligible_count: 5,
  excluded_count: 0,
  up_count: 3,
  breadth: 0.6,
  return: 0.04,
  excess_vs_market: 0,
  stocks: [{
    stock_id: 'sample-1', ticker: 'SAMP', name: 'Sample stock', return: 0.08,
    excess_vs_sector: 0.04, comparison_close: 100, final_close: 108,
    final_observation_status: 'final', data_as_of: '2026-01-02T00:00:00Z', data_as_of_kind: 'provider',
  }],
}

describe('private sample tables', () => {
  it('names the unclassified group and omits its self-comparison', () => {
    const html = renderToStaticMarkup(<SectorTable sectors={[sampleGroup]} selectedCode="UNCLASSIFIED" onSelect={() => {}} isPrivateSample />)

    expect(html).toContain('aria-label="Sample group table"')
    expect(html).toContain('>Group</th>')
    expect(html).not.toContain('>Sector</th>')
    expect(html).not.toContain('>Rank</th>')
    expect(html).not.toContain('vs market')
  })

  it('compares stock returns with the sample, not a sector or a separate market', () => {
    const html = renderToStaticMarkup(<StockTable sector={sampleGroup} marketReturn={0.04} isPrivateSample />)

    expect(html).toContain('>Sample</th>')
    expect(html).toContain('>vs sample</th>')
    expect(html).toContain('+4.0 pp')
    expect(html).not.toContain('>Sector</th>')
    expect(html).not.toContain('>Market</th>')
  })
})
