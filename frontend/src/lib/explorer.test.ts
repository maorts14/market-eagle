import { beforeAll, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { getFixtureExplorer } from './explorer'

const publicFixture = resolve(import.meta.dirname, '../../public/fixtures')
const expected = JSON.parse(readFileSync(resolve(import.meta.dirname, '../../../fixtures/synthetic-v1/expected-results.json'), 'utf8')).explorer

beforeAll(() => {
  vi.stubGlobal('fetch', async (url: string) => ({
    text: async () => readFileSync(resolve(publicFixture, String(url).split('/').at(-1)!), 'utf8'),
  }))
})

describe('synthetic explorer adapter', () => {
  it.each([
    ['full_2025', '2025-01-01', '2025-12-31'],
    ['december_2025', '2025-12-01', '2025-12-31'],
  ])('matches committed %s expectations', async (key, start, end) => {
    const result = await getFixtureExplorer({ start, end })
    const facts = expected[key]
    expect(result.resolved_window).toEqual({
      comparison_session: facts.comparison_session,
      first_session: facts.first_session,
      last_session: facts.last_session,
    })
    expect(result.catalog.tracked_count).toBe(facts.tracked_count)
    expect(result.market.eligible_count).toBe(facts.eligible_count)
    expect(result.market.return).toBeCloseTo(facts.market_return, 10)
    for (const [code, sectorFacts] of Object.entries(facts.sectors) as [string, { eligible_count: number; up_count: number; breadth: number; return: number }][]) {
      const sector = result.sectors.find((row) => row.sector_code === code)!
      expect(sector.eligible_count).toBe(sectorFacts.eligible_count)
      expect(sector.up_count).toBe(sectorFacts.up_count)
      expect(sector.breadth).toBe(sectorFacts.breadth)
      expect(sector.return).toBeCloseTo(sectorFacts.return, 10)
    }
    for (const [ticker, stockFacts] of Object.entries(facts.stocks) as [string, { return: number; sector_code: string }][]) {
      const sector = result.sectors.find((row) => row.sector_code === stockFacts.sector_code)!
      expect(sector.stocks.find((row) => row.ticker === ticker)?.return).toBeCloseTo(stockFacts.return, 10)
    }
    expect(result.data.synthetic).toBe(true)
  })

  it('rejects a window without comparable sessions', async () => {
    await expect(getFixtureExplorer({ start: '2026-01-01', end: '2026-01-31' })).rejects.toMatchObject({ code: 'no_sessions' })
  })
})
