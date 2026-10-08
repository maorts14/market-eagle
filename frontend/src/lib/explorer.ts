export type WindowDates = { start: string; end: string }

export type ExplorerStock = {
  stock_id: string
  ticker: string
  name: string
  return: number
  excess_vs_sector: number
  comparison_close: number
  final_close: number
  final_observation_status: string
  data_as_of: string
  data_as_of_kind: 'provider' | 'fetched'
}

export type ExplorerSector = {
  sector_code: string
  sector_name: string
  tracked_count: number
  eligible_count: number
  excluded_count: number
  up_count: number
  breadth: number | null
  return: number | null
  excess_vs_market: number | null
  stocks: ExplorerStock[]
}

export type ExplorerResponse = {
  contract_version: 1
  metric_version: 'return-v1'
  requested_window: WindowDates
  resolved_window: {
    comparison_session: string
    first_session: string
    last_session: string
  }
  catalog: {
    snapshot_id: string
    as_of: string
    published_at: string
    tracked_count: number
  }
  data: {
    source: string
    feed: string
    price_basis: string
    as_of: string | null
    as_of_kind: 'provider' | 'fetched' | 'mixed' | null
    provisional: boolean
    synthetic: boolean
  }
  market: {
    eligible_count: number
    excluded_count: number
    return: number | null
  }
  sectors: ExplorerSector[]
}

export class ExplorerError extends Error {
  code: string

  constructor(message: string, code: string) {
    super(message)
    this.code = code
  }
}

type CatalogRow = {
  snapshot_id: string
  catalog_as_of: string
  published_at: string
  stock_id: string
  ticker: string
  name: string
  sector_code: string
  sector_name: string
}

type BarRow = {
  stock_id: string
  session_date: string
  close: string
  provider_as_of: string
  status: string
}

function parseCsv<T>(content: string): T[] {
  const [header, ...lines] = content.trim().split(/\r?\n/)
  const columns = header.split(',')
  return lines.map((line) => Object.fromEntries(
    line.split(',').map((value, index) => [columns[index], value]),
  ) as T)
}

let fixturePromise: Promise<{ catalog: CatalogRow[]; bars: BarRow[]; sessions: string[] }> | undefined

async function loadFixture() {
  fixturePromise ??= Promise.all([
    fetch('/fixtures/catalog.csv').then((response) => response.text()),
    fetch('/fixtures/bars.csv').then((response) => response.text()),
    fetch('/fixtures/sessions.csv').then((response) => response.text()),
  ]).then(([catalog, bars, sessions]) => ({
    catalog: parseCsv<CatalogRow>(catalog),
    bars: parseCsv<BarRow>(bars),
    sessions: sessions.trim().split(/\r?\n/).slice(1),
  })).catch((error) => {
    fixturePromise = undefined
    throw error
  })
  return fixturePromise
}

export async function getFixtureExplorer(window: WindowDates): Promise<ExplorerResponse> {
  if (window.start > window.end) {
    throw new ExplorerError('The start date must be on or before the end date.', 'invalid_range')
  }

  const { catalog, bars, sessions } = await loadFixture()
  const included = sessions.filter((session) => session >= window.start && session <= window.end)
  const first = included[0]
  const last = included.at(-1)
  const previous = sessions[sessions.indexOf(first) - 1]
  if (!first || !last || !previous) {
    throw new ExplorerError('No comparable sample sessions fall in this window. Choose dates within 2024–2025.', 'no_sessions')
  }

  const byStock = new Map<string, Map<string, BarRow>>()
  for (const bar of bars) {
    if (!byStock.has(bar.stock_id)) byStock.set(bar.stock_id, new Map())
    byStock.get(bar.stock_id)!.set(bar.session_date, bar)
  }

  const grouped = new Map<string, ExplorerSector>()
  for (const stock of catalog) {
    let sector = grouped.get(stock.sector_code)
    if (!sector) {
      sector = {
        sector_code: stock.sector_code,
        sector_name: stock.sector_name,
        tracked_count: 0,
        eligible_count: 0,
        excluded_count: 0,
        up_count: 0,
        breadth: null,
        return: null,
        excess_vs_market: null,
        stocks: [],
      }
      grouped.set(stock.sector_code, sector)
    }
    sector.tracked_count++
    const comparison = byStock.get(stock.stock_id)?.get(previous)
    const final = byStock.get(stock.stock_id)?.get(last)
    if (!comparison || !final) {
      sector.excluded_count++
      continue
    }
    const comparisonClose = Number(comparison.close)
    const finalClose = Number(final.close)
    const stockReturn = finalClose / comparisonClose - 1
    sector.stocks.push({
      stock_id: stock.stock_id,
      ticker: stock.ticker,
      name: stock.name,
      return: stockReturn,
      excess_vs_sector: 0,
      comparison_close: comparisonClose,
      final_close: finalClose,
      final_observation_status: final.status,
      data_as_of: final.provider_as_of,
      data_as_of_kind: 'provider',
    })
    sector.eligible_count++
    if (stockReturn > 0) sector.up_count++
  }

  const sectors = [...grouped.values()]
  const allReturns = sectors.flatMap((sector) => sector.stocks.map((stock) => stock.return))
  const marketReturn = allReturns.length
    ? allReturns.reduce((sum, value) => sum + value, 0) / allReturns.length
    : null

  for (const sector of sectors) {
    if (!sector.eligible_count) continue
    sector.breadth = sector.up_count / sector.eligible_count
    sector.return = sector.stocks.reduce((sum, stock) => sum + stock.return, 0) / sector.eligible_count
    sector.excess_vs_market = marketReturn === null ? null : sector.return - marketReturn
    sector.stocks = sector.stocks
      .map((stock) => ({ ...stock, excess_vs_sector: stock.return - sector.return! }))
      .sort((a, b) => b.excess_vs_sector - a.excess_vs_sector || a.ticker.localeCompare(b.ticker))
  }
  sectors.sort((a, b) => (b.breadth ?? -1) - (a.breadth ?? -1) || a.sector_code.localeCompare(b.sector_code))

  const finalBars = sectors.flatMap((sector) => sector.stocks)
  return {
    contract_version: 1,
    metric_version: 'return-v1',
    requested_window: window,
    resolved_window: { comparison_session: previous, first_session: first, last_session: last },
    catalog: {
      snapshot_id: catalog[0].snapshot_id,
      as_of: catalog[0].catalog_as_of,
      published_at: catalog[0].published_at,
      tracked_count: catalog.length,
    },
    data: {
      source: 'synthetic-v1',
      feed: 'fictional',
      price_basis: 'synthetic_raw',
      as_of: finalBars.length
        ? finalBars.reduce((earliest, stock) => stock.data_as_of < earliest ? stock.data_as_of : earliest, finalBars[0].data_as_of)
        : null,
      as_of_kind: finalBars.length ? 'provider' : null,
      provisional: finalBars.some((stock) => stock.final_observation_status === 'provisional'),
      synthetic: true,
    },
    market: {
      eligible_count: allReturns.length,
      excluded_count: catalog.length - allReturns.length,
      return: marketReturn,
    },
    sectors,
  }
}

export async function getExplorer(window: WindowDates): Promise<ExplorerResponse> {
  if (import.meta.env.VITE_EXPLORER_MODE !== 'api') return getFixtureExplorer(window)
  const parameters = new URLSearchParams(window)
  const response = await fetch(`/api/v1/explorer?${parameters}`)
  const payload = await response.json()
  if (!response.ok) {
    throw new ExplorerError(payload.error?.message ?? 'The explorer could not load this window.', payload.error?.code ?? 'request_failed')
  }
  return payload as ExplorerResponse
}
