import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { ArrowUp, ChevronDown, CircleStop, Plus, RotateCcw, Trash2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'
import {
  agent, agentMode, AgentApiError, exampleQuestion, followUpQuestion,
  type AgentConversation, type AgentConversationSummary, type AgentRow, type AgentSortMeasure, type AgentTurn, type TrustedResult,
} from '@/lib/agent'
import { isSyntheticTestData, syntheticApiTest } from '@/lib/mode'
import './AgentResearch.css'

const activeStatuses = new Set(['running', 'cancel_requested'])
const syntheticApiQuestion = 'Which stock gained most while daily dollar trading volume exceeded $100,000 on at least 80% of observed days from December 1 to December 31, 2025?'

function percent(value: number | string | null | undefined, signed = false) {
  if (value == null) return '—'
  const numeric = Number(value)
  return `${signed && numeric > 0 ? '+' : ''}${(numeric * 100).toFixed(1)}%`
}

function points(value: number | string | null | undefined) {
  if (value == null) return '—'
  const numeric = Number(value)
  return `${numeric > 0 ? '+' : ''}${(numeric * 100).toFixed(1)} pp`
}

function shortDate(value: string) {
  return new Intl.DateTimeFormat('en-US', { dateStyle: 'medium', timeZone: 'UTC' }).format(new Date(`${value}T12:00:00Z`))
}

function asOf(value: string | null) {
  if (!value) return 'Unavailable'
  return new Intl.DateTimeFormat('en-US', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' }).format(new Date(value)) + ' UTC'
}

function rowTitle(row: AgentRow) {
  return row.ticker ?? row.sector_code ?? 'Result'
}

function resultMetric(row: AgentRow, sortMeasure?: AgentSortMeasure) {
  switch (sortMeasure) {
    case 'period_return': return { label: 'Period return', value: percent(row.period_return, true) }
    case 'excess_vs_sector': return { label: 'Excess vs sector', value: points(row.excess_vs_sector) }
    case 'breadth': return { label: 'Sector breadth', value: percent(row.breadth) }
    case 'sector_return': return { label: 'Sector return', value: percent(row.sector_return, true) }
    case 'qualifying_fraction': return { label: 'Qualifying share', value: percent(row.qualifying_fraction) }
    case 'qualifying_days': return { label: 'Qualifying days', value: row.qualifying_days == null ? '—' : `${row.qualifying_days} days` }
  }
  if (row.period_return != null) return { label: 'Period return', value: percent(row.period_return, true) }
  if (row.qualifying_fraction != null) return { label: 'Qualifying share', value: percent(row.qualifying_fraction) }
  if (row.breadth != null) return { label: 'Sector breadth', value: percent(row.breadth) }
  return { label: 'Sector return', value: percent(row.sector_return, true) }
}

function Evidence({ result }: { result: TrustedResult }) {
  return <details className="agent-evidence">
    <summary>Calculation and source evidence <ChevronDown size={15} aria-hidden="true" /></summary>
    <div className="agent-evidence-body">
      <dl className="agent-evidence-grid">
        <div><dt>Requested dates</dt><dd>{shortDate(result.requested_window.start)} – {shortDate(result.requested_window.end)}</dd></div>
        <div><dt>Resolved sessions</dt><dd>{shortDate(result.resolved_window.first_session)} – {shortDate(result.resolved_window.last_session)}</dd></div>
        <div><dt>Comparison close</dt><dd>{result.resolved_window.comparison_session ? shortDate(result.resolved_window.comparison_session) : 'None required for frequency-only result'}</dd></div>
        <div><dt>Eligible coverage</dt><dd>{result.eligible_count} of {result.catalog.tracked_count} tracked · {percent(result.eligible_count / result.catalog.tracked_count)}</dd></div>
        <div><dt>Source / feed</dt><dd>{result.data.source} / {result.data.feed}</dd></div>
        <div><dt>Price basis</dt><dd>{result.data.price_basis}</dd></div>
        <div><dt>{result.data.as_of_kind === 'fetched' ? 'Collected at' : result.data.as_of_kind === 'mixed' ? 'Earliest source time' : 'Data as of'}</dt><dd>{asOf(result.data.as_of)}{result.data.as_of_kind === 'fetched' ? ' · not provider publication' : result.data.as_of_kind === 'mixed' ? ' · provider and collection times mixed' : ''}{result.data.provisional ? ' · provisional' : ''}</dd></div>
        <div><dt>Current catalog as of</dt><dd>{shortDate(result.catalog.as_of)} · {result.catalog.snapshot_id}{result.catalog.provisional ? ' · provisional public membership and sectors' : ''}</dd></div>
        <div><dt>Calculated at</dt><dd>{asOf(result.calculated_at)}</dd></div>
        <div><dt>Matched candidates</dt><dd>{result.matched_count}</dd></div>
      </dl>
      {result.rows.length > 0 && <div className="agent-evidence-rows"><h4>Returned rows</h4>{result.rows.map((row, index) => <dl className="agent-evidence-row" key={`${rowTitle(row)}-${index}`}>
        <div><dt>Stock / sector</dt><dd>{rowTitle(row)}{row.name ? ` · ${row.name}` : ''}</dd></div>
        {row.period_return != null && <div><dt>Period return</dt><dd>{percent(row.period_return, true)}</dd></div>}
        {row.excess_vs_sector != null && <div><dt>Excess vs sector</dt><dd>{points(row.excess_vs_sector)}</dd></div>}
        {row.qualifying_fraction != null && <div><dt>Qualifying share</dt><dd>{percent(row.qualifying_fraction)}</dd></div>}
        {row.breadth != null && <div><dt>Breadth</dt><dd>{percent(row.breadth)}</dd></div>}
        {row.qualifying_days != null && <div><dt>Qualifying / observed days</dt><dd>{row.qualifying_days} / {row.observed_usable_days}</dd></div>}
        {row.requested_sessions != null && <div><dt>Requested sessions</dt><dd>{row.requested_sessions} · {percent(row.requested_coverage)} observed</dd></div>}
        {row.dollar_volume_formulas?.map((formula) => <div key={formula.input}><dt>Dollar-volume input</dt><dd>{formula.formula}{formula.estimated ? ' · estimate' : ''}</dd></div>)}
      </dl>)}</div>}
      {result.exclusions.length > 0 && <p className="agent-exclusions">Excluded: {result.exclusions.map((item) => `${item.ticker ?? item.stock_id} (${item.reason.replaceAll('_', ' ')})`).join(', ')}.</p>}
      <p className="agent-policy">{result.data.synthetic ? 'Fictional synthetic history; weekdays are not an exchange calendar.' : 'Selected source and basis are shown above.'}{!result.data.return_rankings_trusted && result.rows.some((row) => row.period_return != null) && ' Return rankings remain untrusted until the live price basis is settled.'}</p>
    </div>
  </details>
}

export function TurnCard({ turn }: { turn: AgentTurn }) {
  const mismatchedTestResult = syntheticApiTest && turn.trusted_result && !isSyntheticTestData(turn.trusted_result.data)
  const result = mismatchedTestResult ? null : turn.trusted_result
  const lead = result?.rows[0]
  const sortMeasure = turn.decision?.request?.sort.measure
  const metric = lead ? resultMetric(lead, sortMeasure) : null
  return <article className="agent-turn" aria-label={`Question: ${turn.question}`}>
    <div className="agent-question"><span>Question</span><p>{turn.question}</p></div>
    {activeStatuses.has(turn.status) && <div className="agent-progress" role="status"><span className="agent-pulse" aria-hidden="true" />{turn.status === 'cancel_requested' ? 'Stopping this turn…' : 'Analysis in progress. You can leave and return to this conversation.'}</div>}
    {mismatchedTestResult && <div className="agent-state-message error" role="alert"><strong>Test data mismatch</strong><p>The agent returned data outside synthetic-v1. Check the isolated test worker configuration.</p></div>}
    {result && turn.status === 'failed' && <div className="agent-state-message error" role="alert"><strong>Turn failed after verification</strong><p>The verified calculation remains available below, but the turn did not complete.</p></div>}
    {result && <div className="agent-answer">
      <div className="agent-result-heading"><span>Verified calculation</span>{result.data.synthetic && <Badge variant="outline">SYNTHETIC</Badge>}{result.catalog.scope === 'private_five_stock_sample' && <Badge variant="outline">PRIVATE FIVE-STOCK SAMPLE · NOT S&amp;P 500</Badge>}</div>
      {result.rows.length > 1 ? <div className="agent-ranked-results">
        <h4>Ranked results</h4>
        <Table aria-label="Verified ranked results" className="agent-ranking-table">
          <TableHeader><TableRow><TableHead scope="col">Rank</TableHead><TableHead scope="col">Stock / sector</TableHead><TableHead scope="col">{metric?.label}</TableHead></TableRow></TableHeader>
          <TableBody>{result.rows.map((row, index) => <TableRow key={`${rowTitle(row)}-${index}`}>
            <TableCell>{index + 1}</TableCell>
            <TableCell><strong>{rowTitle(row)}</strong>{row.name && <span>{row.name}</span>}</TableCell>
            <TableCell><strong>{resultMetric(row, sortMeasure).value}</strong>{row.qualifying_days != null && <span>{row.qualifying_days} / {row.observed_usable_days} observed days</span>}</TableCell>
          </TableRow>)}</TableBody>
        </Table>
        {result.matched_count > result.rows.length && <p>Showing {result.rows.length} of {result.matched_count} matches.</p>}
      </div> : lead ? <><div className="agent-result-main"><div><strong>{rowTitle(lead)}</strong>{lead.name && <span>{lead.name}</span>}</div><div><span>{metric?.label}</span><strong>{metric?.value}</strong></div></div>{lead.qualifying_days != null && <p className="agent-observation">{lead.qualifying_days} of {lead.observed_usable_days} observed usable days qualified{lead.requested_sessions != null ? ` · ${lead.requested_sessions} sessions requested` : ''}</p>}</> : <p>No rows matched the validated request in the evaluated data.</p>}
      <p className="agent-coverage">{result.coverage_label}. {result.ranking_scope === 'eligible_stocks_only' ? 'Ranking applies to eligible stocks only.' : ''}</p>
      {turn.agent_explanation && <div className="agent-interpretation"><h4>Interpretation</h4><p>{turn.agent_explanation}</p></div>}
      {turn.status === 'completed' && !turn.agent_explanation && <div className="agent-interpretation"><h4>Interpretation unavailable</h4><p>The verified calculation and source evidence remain available.</p></div>}
      {turn.decision?.assumptions && turn.decision.assumptions.length > 0 && <div className="agent-assumptions"><h4>Assumptions</h4><ul>{turn.decision.assumptions.map((assumption) => <li key={assumption}>{assumption}</li>)}</ul></div>}
      <Evidence result={result} />
    </div>}
    {!result && turn.status === 'needs_clarification' && <div className="agent-state-message"><strong>Clarification needed</strong><p>{turn.agent_explanation ?? turn.decision?.message}</p><span>Reply below in this conversation.</span></div>}
    {!result && turn.status === 'unsupported' && <div className="agent-state-message"><strong>Request unsupported</strong><p>{turn.agent_explanation ?? turn.decision?.message}</p></div>}
    {!result && turn.status === 'failed' && <div className="agent-state-message error"><strong>Analysis failed</strong><p>{turn.error ?? 'The turn could not be completed. You can retry with a new question.'}</p></div>}
    {!result && turn.status === 'cancelled' && <div className="agent-state-message"><strong>Turn cancelled</strong><p>You can ask another question in this conversation.</p></div>}
  </article>
}

export default function AgentResearch() {
  const [conversations, setConversations] = useState<AgentConversationSummary[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [turns, setTurns] = useState<AgentTurn[]>([])
  const [draft, setDraft] = useState('')
  const [listing, setListing] = useState(true)
  const [loadedId, setLoadedId] = useState('')
  const [acting, setActing] = useState(false)
  const [error, setError] = useState('')
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [syncStopped, setSyncStopped] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)
  const requestRef = useRef<{ question: string; id: string } | null>(null)
  const conversationRef = useRef<HTMLDivElement>(null)
  const activeTurn = turns.find((turn) => turn.conversation_id === selectedId && activeStatuses.has(turn.status))
  const loading = Boolean(selectedId && loadedId !== selectedId)

  const applyConversations = useCallback((listed: AgentConversationSummary[], preferredId?: string) => {
    setConversations(listed)
    setSelectedId((current) => {
      if (preferredId && listed.some((item) => item.conversation_id === preferredId)) return preferredId
      if (listed.some((item) => item.conversation_id === current)) return current
      return listed[0]?.conversation_id ?? ''
    })
  }, [])

  const refreshConversations = useCallback(async (preferredId?: string) => {
    setListing(true)
    try { applyConversations(await agent.listConversations(), preferredId) }
    finally { setListing(false) }
  }, [applyConversations])

  useEffect(() => {
    let live = true
    agent.listConversations().then((listed) => { if (live) applyConversations(listed) })
      .catch((reason: Error) => { if (live) setError(`Could not list conversations: ${reason.message}`) })
      .finally(() => { if (live) setListing(false) })
    return () => { live = false }
  }, [applyConversations])

  useEffect(() => {
    const panel = conversationRef.current
    if (panel) panel.scrollTop = panel.scrollHeight
  }, [turns.length, selectedId])

  useEffect(() => {
    if (!selectedId) return
    let live = true
    agent.getConversation(selectedId).then((current: AgentConversation) => {
      if (!live) return
      setTurns(current.turns)
      setError('')
      setSyncStopped(false)
    }).catch((reason: Error) => { if (live) setError(`Could not load this conversation: ${reason.message}`) })
      .finally(() => { if (live) setLoadedId(selectedId) })
    return () => { live = false }
  }, [selectedId, reloadKey])

  useEffect(() => {
    if (!activeTurn || activeTurn.conversation_id !== selectedId || syncStopped) return
    let live = true
    const timer = window.setTimeout(async () => {
      try {
        const updated = await agent.getTurn(activeTurn.turn_id)
        if (live) setTurns((current) => current.map((turn) => turn.turn_id === updated.turn_id ? updated : turn))
      } catch (reason) {
        if (live) {
          setSyncStopped(true)
          setError(`Connection interrupted. This turn is saved; reconnect to check its status. ${reason instanceof Error ? reason.message : ''}`)
        }
      }
    }, 1400)
    return () => { live = false; window.clearTimeout(timer) }
  }, [activeTurn, selectedId, syncStopped])

  async function createConversation() {
    setActing(true)
    setError('')
    try {
      const id = await agent.createConversation()
      setTurns([])
      setDraft('')
      setConfirmDelete(false)
      try { await refreshConversations(id) }
      catch (reason) { setError(`Conversation created, but the list could not refresh: ${reason instanceof Error ? reason.message : 'Unknown error.'}`) }
    } catch (reason) { setError(`Could not create a conversation: ${reason instanceof Error ? reason.message : 'Unknown error.'}`) }
    finally { setActing(false) }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const question = draft.trim()
    if (!selectedId || !question || activeTurn || acting) return
    const requestId = requestRef.current?.question === question ? requestRef.current.id : crypto.randomUUID()
    requestRef.current = { question, id: requestId }
    setActing(true)
    setError('')
    try {
      const turn = await agent.submitTurn(selectedId, question, requestId)
      setTurns((current) => current.some((item) => item.turn_id === turn.turn_id) ? current : [...current, turn])
      setDraft('')
      requestRef.current = null
      try { await refreshConversations(selectedId) }
      catch (reason) { setError(`Question saved, but the conversation list could not refresh: ${reason instanceof Error ? reason.message : 'Unknown error.'}`) }
    } catch (reason) {
      setError(`Question was not accepted: ${reason instanceof Error ? reason.message : 'Unknown error.'} Retry will use the same request ID.`)
      if (reason instanceof AgentApiError && reason.status === 409) { setLoadedId(''); setReloadKey((key) => key + 1) }
    } finally { setActing(false) }
  }

  async function cancel() {
    if (!activeTurn || acting) return
    setActing(true)
    setError('')
    try {
      const updated = await agent.cancelTurn(activeTurn.turn_id)
      setTurns((current) => current.map((turn) => turn.turn_id === updated.turn_id ? updated : turn))
    } catch (reason) { setError(`Could not cancel this turn: ${reason instanceof Error ? reason.message : 'Unknown error.'}`) }
    finally { setActing(false) }
  }

  async function removeConversation() {
    if (!selectedId || acting) return
    setActing(true)
    setError('')
    try {
      await agent.deleteConversation(selectedId)
      const next = conversations.filter((item) => item.conversation_id !== selectedId)
      setConversations(next)
      setSelectedId(next[0]?.conversation_id ?? '')
      setTurns([])
      setConfirmDelete(false)
      try { await refreshConversations() }
      catch (reason) { setError(`Conversation deleted, but the list could not refresh: ${reason instanceof Error ? reason.message : 'Unknown error.'}`) }
    } catch (reason) { setError(`Could not delete this conversation: ${reason instanceof Error ? reason.message : 'Unknown error.'}`) }
    finally { setActing(false) }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') event.currentTarget.form?.requestSubmit()
  }

  async function reconnect() {
    setError('')
    try {
      await refreshConversations()
      setSyncStopped(false)
      setLoadedId('')
      setReloadKey((key) => key + 1)
    } catch (reason) { setError(`Could not refresh conversations: ${reason instanceof Error ? reason.message : 'Unknown error.'}`) }
  }

  return <section className="agent-section" aria-labelledby="agent-heading">
    <div className="agent-header"><div><h2 id="agent-heading">Research conversation</h2><p>Research questions over retained market observations.</p></div><Badge variant="outline" className="agent-mode">{syntheticApiTest ? 'SYNTHETIC API TEST' : agentMode === 'fixture' ? 'SYNTHETIC AGENT DEMO' : 'AGENT API'}</Badge></div>
    <div className="agent-toolbar"><label htmlFor="conversation-select">Conversation</label><select id="conversation-select" value={selectedId} onChange={(event) => { setTurns([]); setSelectedId(event.target.value); setConfirmDelete(false); setDraft('') }} disabled={listing || !conversations.length || acting}>{conversations.length ? conversations.map((item) => <option key={item.conversation_id} value={item.conversation_id}>{item.title}</option>) : <option value="">No conversation yet</option>}</select><Button type="button" variant="outline" size="sm" disabled={listing || acting} onClick={createConversation}><Plus size={15} aria-hidden="true" />New</Button><Button type="button" variant="ghost" size="sm" disabled={listing || acting} onClick={reconnect}><RotateCcw size={15} aria-hidden="true" />Refresh</Button>{selectedId && <Button type="button" variant="ghost" size="sm" className="agent-delete" disabled={listing || acting} onClick={() => setConfirmDelete(true)}><Trash2 size={15} aria-hidden="true" />Delete</Button>}<span>{agentMode === 'fixture' ? 'Local fixture conversations' : 'All conversations'}</span></div>
    {confirmDelete && <div className="agent-delete-confirm" role="group" aria-label="Confirm conversation deletion"><p><strong>Delete this conversation permanently?</strong> {agentMode === 'api' ? 'It will disappear for every visitor. ' : ''}Its turns and evidence cannot be recovered. The initial deployment has no backup.</p><div><Button type="button" size="sm" variant="destructive" disabled={acting} onClick={removeConversation}>Delete permanently</Button><Button type="button" size="sm" variant="ghost" onClick={() => setConfirmDelete(false)}>Keep conversation</Button></div></div>}
    {error && <div className="agent-error" role="alert"><p>{error}</p><Button type="button" size="sm" variant="outline" onClick={reconnect}><RotateCcw size={14} aria-hidden="true" />Reconnect</Button></div>}
    <div className="agent-conversation" ref={conversationRef} aria-live="polite">{listing && !selectedId ? <p className="agent-empty">Loading conversations…</p> : loading ? <p className="agent-empty">Loading conversation…</p> : turns.some((turn) => turn.conversation_id === selectedId) ? turns.filter((turn) => turn.conversation_id === selectedId).map((turn) => <TurnCard turn={turn} key={turn.turn_id} />) : <div className="agent-empty"><strong>{selectedId ? 'Start with a research question' : 'Start a conversation'}</strong><p>{selectedId ? 'Questions and follow-ups in this conversation share context.' : 'Create a conversation to ask the research agent. New conversations start fresh.'}</p></div>}</div>
    {activeTurn && <div className="agent-active-actions"><span>{activeTurn.status === 'cancel_requested' ? 'Cancellation requested' : 'One turn is active in this conversation'}</span><Button type="button" size="sm" variant="outline" disabled={acting || activeTurn.status === 'cancel_requested'} onClick={cancel}><CircleStop size={15} aria-hidden="true" />Cancel turn</Button></div>}
    <form className="agent-composer" onSubmit={submit}><label htmlFor="agent-question">{turns.length ? 'Follow-up question' : 'Research question'}</label><div><Textarea id="agent-question" value={draft} onChange={(event) => { setDraft(event.target.value); if (requestRef.current?.question !== event.target.value.trim()) requestRef.current = null }} onKeyDown={handleKeyDown} maxLength={4000} rows={2} placeholder={agentMode === 'fixture' ? 'Use the documented sample question below' : 'Ask about returns, breadth, volume, or coverage'} disabled={!selectedId || Boolean(activeTurn) || acting} /><Button type="submit" disabled={!selectedId || !draft.trim() || Boolean(activeTurn) || acting}><ArrowUp size={16} aria-hidden="true" />Ask</Button></div><div className="agent-composer-foot"><span>{syntheticApiTest ? 'Agent API over fictional 2024–2025 data.' : agentMode === 'fixture' ? 'Local fixture: example and one follow-up only. No model is called.' : 'Answers use validated, read-only calculations.'}</span><span>{draft.length} / 4000 · Ctrl+Enter to send</span></div></form>
    <div className="agent-suggestions"><span>Try</span><button type="button" disabled={!selectedId || Boolean(activeTurn)} onClick={() => setDraft(syntheticApiTest ? syntheticApiQuestion : exampleQuestion)}>{syntheticApiTest ? 'Gain + dollar volume in Dec 2025' : 'Gain + dollar volume last month'}</button>{turns.some((turn) => turn.status === 'completed') && <button type="button" disabled={!selectedId || Boolean(activeTurn)} onClick={() => setDraft(followUpQuestion)}>Ask a follow-up</button>}</div>
  </section>
}
