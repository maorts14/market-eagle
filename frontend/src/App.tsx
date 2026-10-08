import { useEffect, useState } from 'react'
import { ArrowDownRight, ArrowRight, ArrowUpRight, CalendarDays, RefreshCw } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { getExplorer, type ExplorerResponse, type ExplorerSector, type WindowDates } from '@/lib/explorer'
import './App.css'

const fixtureMode = import.meta.env.VITE_EXPLORER_MODE !== 'api'
const sampleEnd = fixtureMode ? '2025-12-31' : new Date().toISOString().slice(0, 10)
const monthStart = (monthsBefore: number) => {
  const date = new Date(`${sampleEnd}T12:00:00Z`)
  date.setUTCDate(1)
  date.setUTCMonth(date.getUTCMonth() - monthsBefore)
  return date.toISOString().slice(0, 10)
}
const presets = [
  { label: '1M', start: monthStart(0), end: sampleEnd },
  { label: '3M', start: monthStart(2), end: sampleEnd },
  { label: '1Y', start: monthStart(11), end: sampleEnd },
]

function percent(value: number | null, signed = false) {
  if (value === null) return '—'
  return `${signed && value > 0 ? '+' : ''}${(value * 100).toFixed(1)}%`
}

function points(value: number | null) {
  if (value === null) return '—'
  return `${value > 0 ? '+' : ''}${(value * 100).toFixed(1)} pp`
}

function valueTone(value: number | null) {
  if (value === null || value === 0) return ''
  return value > 0 ? 'positive' : 'negative'
}

function dateLabel(value: string) {
  return new Intl.DateTimeFormat('en-US', { dateStyle: 'medium', timeZone: 'UTC' }).format(new Date(`${value}T12:00:00Z`))
}

function timeLabel(value: string | null) {
  if (!value) return 'Unknown'
  return new Intl.DateTimeFormat('en-US', {
    dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC',
  }).format(new Date(value)) + ' UTC'
}

function BreadthMark({ breadth }: { breadth: number | null }) {
  return <span className="breadth-mark" aria-hidden="true"><span style={{ width: `${(breadth ?? 0) * 100}%` }} /></span>
}

function SectorTable({ sectors, selectedCode, onSelect }: {
  sectors: ExplorerSector[]
  selectedCode: string | null
  onSelect: (code: string) => void
}) {
  return <><p className="scroll-hint">Scroll table horizontally for all measures →</p><div className="table-scroll" tabIndex={0} role="region" aria-label="Sector comparison table">
    <Table>
      <TableHeader><TableRow>
        <TableHead className="rank-column">Rank</TableHead>
        <TableHead>Sector</TableHead>
        <TableHead className="numeric-column">Up / eligible</TableHead>
        <TableHead className="numeric-column breadth-column">Breadth</TableHead>
        <TableHead className="numeric-column">Return</TableHead>
        <TableHead className="numeric-column">vs market</TableHead>
      </TableRow></TableHeader>
      <TableBody>{sectors.map((sector, index) => <TableRow key={sector.sector_code} className={sector.sector_code === selectedCode ? 'selected-row' : ''}>
        <TableCell className="rank-column muted-number">{String(index + 1).padStart(2, '0')}</TableCell>
        <TableCell><button className="sector-select" type="button" aria-current={sector.sector_code === selectedCode ? 'true' : undefined} aria-label={`Inspect ${sector.sector_name} stocks`} onClick={() => onSelect(sector.sector_code)}><span className="sector-name">{sector.sector_name}</span><ArrowRight size={15} aria-hidden="true" /></button></TableCell>
        <TableCell className="numeric-column count-cell">{sector.up_count} / {sector.eligible_count}<span className="sub-count"> of {sector.tracked_count} tracked</span></TableCell>
        <TableCell className="numeric-column breadth-cell"><BreadthMark breadth={sector.breadth} /><span>{percent(sector.breadth)}</span></TableCell>
        <TableCell className={`numeric-column ${valueTone(sector.return)}`}>{percent(sector.return, true)}</TableCell>
        <TableCell className={`numeric-column ${valueTone(sector.excess_vs_market)}`}>{points(sector.excess_vs_market)}</TableCell>
      </TableRow>)}</TableBody>
    </Table>
  </div></>
}

function StockTable({ sector, marketReturn }: { sector: ExplorerSector; marketReturn: number | null }) {
  if (!sector.stocks.length) return <p className="empty-detail">No stocks have both comparison closes for this window. Try another range.</p>
  return <><p className="scroll-hint">Scroll table horizontally for all measures →</p><div className="table-scroll" tabIndex={0} role="region" aria-label={`${sector.sector_name} stock comparison table`}><Table>
    <TableHeader><TableRow><TableHead>Stock</TableHead><TableHead className="numeric-column">Return</TableHead><TableHead className="numeric-column">Sector</TableHead><TableHead className="numeric-column">Market</TableHead><TableHead className="numeric-column">Excess</TableHead></TableRow></TableHeader>
    <TableBody>{sector.stocks.map((stock) => <TableRow key={stock.stock_id}>
      <TableCell><strong className="ticker">{stock.ticker}</strong><span className="stock-name">{stock.name}{stock.final_observation_status === 'provisional' ? ' · provisional' : ''}</span></TableCell>
      <TableCell className={`numeric-column ${valueTone(stock.return)}`}>{percent(stock.return, true)}</TableCell>
      <TableCell className="numeric-column secondary-value">{percent(sector.return, true)}</TableCell>
      <TableCell className="numeric-column secondary-value">{percent(marketReturn, true)}</TableCell>
      <TableCell className={`numeric-column excess-value ${valueTone(stock.excess_vs_sector)}`}>{points(stock.excess_vs_sector)}</TableCell>
    </TableRow>)}</TableBody>
  </Table></div></>
}

function App() {
  const [draft, setDraft] = useState<WindowDates>({ start: monthStart(0), end: sampleEnd })
  const [window, setWindow] = useState<WindowDates>(draft)
  const [result, setResult] = useState<ExplorerResponse | null>(null)
  const [selectedCode, setSelectedCode] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [requestKey, setRequestKey] = useState(0)

  useEffect(() => {
    let active = true
    getExplorer(window).then((data) => {
      if (!active) return
      setResult(data)
      setSelectedCode((current) => data.sectors.some((sector) => sector.sector_code === current) ? current : (data.sectors[0]?.sector_code ?? null))
      setError('')
    }).catch((reason: unknown) => {
      if (!active) return
      setError(reason instanceof Error ? reason.message : 'The explorer could not load this window.')
      setResult(null)
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [window, requestKey])

  const selected = result?.sectors.find((sector) => sector.sector_code === selectedCode) ?? null
  const selectedPreset = presets.find((preset) => preset.start === window.start && preset.end === window.end)?.label
  const isSynthetic = result?.data.synthetic ?? import.meta.env.VITE_EXPLORER_MODE !== 'api'
  const environmentLabel = result ? (result.data.synthetic ? 'SYNTHETIC SAMPLE' : 'MARKET DATA') : (fixtureMode ? 'SYNTHETIC SAMPLE' : 'API MODE')

  function applyWindow(next: WindowDates) {
    setDraft(next)
    setWindow(next)
    setLoading(true)
  }

  function submitWindow(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!draft.start || !draft.end || draft.start > draft.end) {
      setError('Choose a start date on or before the end date.')
      return
    }
    applyWindow({ ...draft })
  }

  return <div className="app-shell">
    <header className="topbar"><div className="brand"><span className="brand-mark" aria-hidden="true">M<span>E</span></span><span>Market Eagle</span></div><div className="topbar-right"><span className="workspace-label">Research workspace</span><Badge variant="outline" className="environment-badge">{environmentLabel}</Badge></div></header>
    <main className="workspace">
      <div className="heading-row"><div><h1>Sector breadth</h1><p className="page-intro">Compare the share of rising stocks, then inspect the names behind a sector.</p></div>{result && <div className="as-of"><span>DATA AS OF</span><strong>{timeLabel(result.data.as_of)}</strong></div>}</div>
      <section className="control-band" aria-label="Research window"><form className="window-form" onSubmit={submitWindow}><div className="control-label"><CalendarDays size={16} aria-hidden="true" /><span>Window</span></div><label className="date-field"><span>Start</span><Input type="date" value={draft.start} onChange={(event) => setDraft({ ...draft, start: event.target.value })} required /></label><span className="date-arrow" aria-hidden="true">→</span><label className="date-field"><span>End</span><Input type="date" value={draft.end} onChange={(event) => setDraft({ ...draft, end: event.target.value })} required /></label><Button type="submit" disabled={loading}>Apply</Button></form><div className="preset-group" role="group" aria-label="Sample date shortcuts">{presets.map((preset) => <Button key={preset.label} type="button" size="sm" variant={selectedPreset === preset.label ? 'secondary' : 'ghost'} aria-pressed={selectedPreset === preset.label} disabled={loading} onClick={() => applyWindow({ start: preset.start, end: preset.end })}>{preset.label}</Button>)}</div></section>
      <div className="source-strip" aria-live="polite"><span className="source-primary"><span className="status-dot" />{isSynthetic ? 'Fictional fixture data' : (result?.data.source ?? 'Waiting for explorer API')}</span><span>{result ? `${result.data.source} · ${result.data.feed}` : 'Loading source'}</span>{result?.data.provisional && <Badge variant="outline" className="provisional-badge">Provisional daily bar</Badge>}<span className="source-note">Live return basis remains unresolved</span></div>
      {error && <div className="error-banner" role="alert"><div><strong>Window unavailable</strong><p>{error}</p></div><Button variant="outline" size="sm" onClick={() => { setLoading(true); setRequestKey((key) => key + 1) }}><RefreshCw size={14} aria-hidden="true" />Retry</Button></div>}
      {loading && <div className="loading-layout" aria-label="Loading research results"><Skeleton className="h-25 w-full" /><div><Skeleton className="h-80 w-full" /><Skeleton className="h-80 w-full" /></div></div>}
      {!loading && result && <>
        <section className="summary-line" aria-label="Market summary"><div className="summary-measure"><span>Equal-weight market return</span><strong className={valueTone(result.market.return)}>{percent(result.market.return, true)}</strong>{result.market.return !== null && (result.market.return >= 0 ? <ArrowUpRight size={18} aria-hidden="true" /> : <ArrowDownRight size={18} aria-hidden="true" />)}</div><Separator orientation="vertical" className="summary-separator" /><div className="summary-measure"><span>Eligible stocks</span><strong>{result.market.eligible_count} <small>/ {result.catalog.tracked_count}</small></strong></div><div className="summary-context">{result.market.excluded_count} excluded for missing endpoints</div></section>
        <div className="research-grid"><section className="sector-panel" aria-labelledby="sector-heading"><div className="panel-heading"><div><h2 id="sector-heading">Sectors</h2><p>Ranked by breadth · select a row to inspect stocks</p></div><span className="panel-count">{result.sectors.length} sectors</span></div><SectorTable sectors={result.sectors} selectedCode={selectedCode} onSelect={setSelectedCode} /><div className="table-footnote">Breadth uses eligible stocks with a strictly positive return.</div></section>
          <section className="detail-panel" aria-labelledby="detail-heading"><div className="panel-heading detail-heading"><div><h2 id="detail-heading">{selected ? selected.sector_name : 'Selected sector'}</h2><p>{selected ? `${selected.eligible_count} of ${selected.tracked_count} stocks eligible` : 'Choose a sector to inspect its stocks'}</p></div>{selected && <Badge variant="secondary" className="sector-code">{selected.sector_code}</Badge>}</div>{selected && <><div className="detail-summary"><div><span>Sector breadth</span><strong>{percent(selected.breadth)}</strong></div><div><span>Equal-weight return</span><strong className={valueTone(selected.return)}>{percent(selected.return, true)}</strong></div><div><span>vs market</span><strong className={valueTone(selected.excess_vs_market)}>{points(selected.excess_vs_market)}</strong></div></div><div className="stock-heading"><h3>Leading stocks</h3><span>Ranked by excess vs sector</span></div><StockTable sector={selected} marketReturn={result.market.return} /></>}</section></div>
        <footer className="evidence" aria-label="Calculation evidence"><div><h2>Calculation evidence</h2><p>Returns compare the close before the first included session with the final session close. Sector and market returns are equal-weight averages of eligible stocks.</p></div><dl><div><dt>Requested window</dt><dd>{dateLabel(result.requested_window.start)} – {dateLabel(result.requested_window.end)}</dd></div><div><dt>Resolved sessions</dt><dd>{dateLabel(result.resolved_window.first_session)} – {dateLabel(result.resolved_window.last_session)}</dd></div><div><dt>Comparison close</dt><dd>{dateLabel(result.resolved_window.comparison_session)}</dd></div><div><dt>Coverage</dt><dd>{result.market.eligible_count} eligible / {result.catalog.tracked_count} tracked · {result.market.excluded_count} excluded</dd></div><div><dt>Data source / feed</dt><dd>{result.data.source} / {result.data.feed}</dd></div><div><dt>Price basis</dt><dd>{result.data.price_basis} {result.data.synthetic ? '· fictional, unadjusted sample' : '· live policy unresolved'}</dd></div><div><dt>Data as of</dt><dd>{timeLabel(result.data.as_of)}{result.data.provisional ? ' · provisional' : ''}</dd></div><div><dt>Current catalog as of</dt><dd>{dateLabel(result.catalog.as_of)} · {result.catalog.snapshot_id}</dd></div></dl><p className="evidence-caveat">{result.data.synthetic ? 'Synthetic weekdays are not an exchange calendar. These numbers are fictional and are for interface and calculation verification only.' : 'Return rankings remain untrusted until the production price adjustment basis is chosen.'}</p></footer>
      </>}
    </main>
  </div>
}

export default App
