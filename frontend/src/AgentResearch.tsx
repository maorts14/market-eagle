import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { ArrowUp, ChevronDown, CircleStop, Plus, RotateCcw, Trash2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import {
  agent, agentMode, AgentApiError, exampleQuestion, followUpQuestion,
  type AgentConversation, type AgentRow, type AgentTurn, type TrustedResult,
} from '@/lib/agent'
import './AgentResearch.css'

type SavedConversation = { id: string; title: string }
const savedKey = `market-eagle-agent-conversations-v1-${agentMode}`
const activeStatuses = new Set(['running', 'cancel_requested'])

function readSaved(): SavedConversation[] {
  return JSON.parse(localStorage.getItem(savedKey) ?? '[]') as SavedConversation[]
}

function saveConversations(items: SavedConversation[]) {
  localStorage.setItem(savedKey, JSON.stringify(items))
}

function percent(value: number | null | undefined, signed = false) {
  if (value == null) return '—'
  return `${signed && value > 0 ? '+' : ''}${(value * 100).toFixed(1)}%`
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

function resultMetric(row: AgentRow) {
  if (row.period_return != null) return { label: 'Period return', value: percent(row.period_return, true) }
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
        <div><dt>Comparison close</dt><dd>{shortDate(result.resolved_window.comparison_session)}</dd></div>
        <div><dt>Eligible coverage</dt><dd>{result.eligible_count} of {result.catalog.tracked_count} tracked · {percent(result.eligible_count / result.catalog.tracked_count)}</dd></div>
        <div><dt>Source / feed</dt><dd>{result.data.source} / {result.data.feed}</dd></div>
        <div><dt>Price basis</dt><dd>{result.data.price_basis}</dd></div>
        <div><dt>{result.data.as_of_kind === 'fetched' ? 'Collected at' : result.data.as_of_kind === 'mixed' ? 'Earliest source time' : 'Data as of'}</dt><dd>{asOf(result.data.as_of)}{result.data.as_of_kind === 'fetched' ? ' · not provider publication' : result.data.as_of_kind === 'mixed' ? ' · provider and collection times mixed' : ''}{result.data.provisional ? ' · provisional' : ''}</dd></div>
        <div><dt>Current catalog as of</dt><dd>{shortDate(result.catalog.as_of)} · {result.catalog.snapshot_id}</dd></div>
        <div><dt>Calculated at</dt><dd>{asOf(result.calculated_at)}</dd></div>
        <div><dt>Matched candidates</dt><dd>{result.matched_count}</dd></div>
      </dl>
      {result.rows.length > 0 && <div className="agent-evidence-rows"><h4>Returned rows</h4>{result.rows.map((row, index) => <dl className="agent-evidence-row" key={`${rowTitle(row)}-${index}`}>
        <div><dt>Stock / sector</dt><dd>{rowTitle(row)}{row.name ? ` · ${row.name}` : ''}</dd></div>
        {row.period_return != null && <div><dt>Period return</dt><dd>{percent(row.period_return, true)}</dd></div>}
        {row.breadth != null && <div><dt>Breadth</dt><dd>{percent(row.breadth)}</dd></div>}
        {row.qualifying_days != null && <div><dt>Qualifying / observed days</dt><dd>{row.qualifying_days} / {row.observed_usable_days}</dd></div>}
        {row.requested_sessions != null && <div><dt>Requested sessions</dt><dd>{row.requested_sessions} · {percent(row.requested_coverage)} observed</dd></div>}
        {row.dollar_volume_formulas?.map((formula) => <div key={formula.input}><dt>Dollar-volume input</dt><dd>{formula.formula}{formula.estimated ? ' · estimate' : ''}</dd></div>)}
      </dl>)}</div>}
      {result.exclusions.length > 0 && <p className="agent-exclusions">Excluded: {result.exclusions.map((item) => `${item.ticker ?? item.stock_id} (${item.reason.replaceAll('_', ' ')})`).join(', ')}.</p>}
      <p className="agent-policy">{result.data.synthetic ? 'Fictional synthetic history; weekdays are not an exchange calendar.' : 'Selected source and basis are shown above.'}{!result.data.return_rankings_trusted && ' Return rankings remain untrusted until the live price basis is settled.'}</p>
    </div>
  </details>
}

function TurnCard({ turn }: { turn: AgentTurn }) {
  const result = turn.trusted_result
  const lead = result?.rows[0]
  const metric = lead ? resultMetric(lead) : null
  return <article className="agent-turn" aria-label={`Question: ${turn.question}`}>
    <div className="agent-question"><span>Question</span><p>{turn.question}</p></div>
    {activeStatuses.has(turn.status) && <div className="agent-progress" role="status"><span className="agent-pulse" aria-hidden="true" />{turn.status === 'cancel_requested' ? 'Stopping this turn…' : 'Analysis in progress. You can leave and return to this conversation.'}</div>}
    {result && <div className="agent-answer">
      <div className="agent-result-heading"><span>Verified calculation</span>{result.data.synthetic && <Badge variant="outline">SYNTHETIC</Badge>}</div>
      {lead ? <div className="agent-result-main"><div><strong>{rowTitle(lead)}</strong>{lead.name && <span>{lead.name}</span>}</div><div><span>{metric?.label}</span><strong>{metric?.value}</strong></div></div> : <p>No rows matched the validated request in the evaluated data.</p>}
      {lead?.qualifying_days != null && <p className="agent-observation">{lead.qualifying_days} of {lead.observed_usable_days} observed usable days qualified{lead.requested_sessions != null ? ` · ${lead.requested_sessions} sessions requested` : ''}</p>}
      <p className="agent-coverage">{result.coverage_label}. {result.ranking_scope === 'eligible_stocks_only' ? 'Ranking applies to eligible stocks only.' : ''}</p>
      {turn.agent_explanation && <div className="agent-interpretation"><h4>Interpretation</h4><p>{turn.agent_explanation}</p></div>}
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
  const [saved, setSaved] = useState<SavedConversation[]>(readSaved)
  const [selectedId, setSelectedId] = useState(() => readSaved()[0]?.id ?? '')
  const [turns, setTurns] = useState<AgentTurn[]>([])
  const [draft, setDraft] = useState('')
  const [loading, setLoading] = useState(() => Boolean(readSaved()[0]?.id))
  const [acting, setActing] = useState(false)
  const [error, setError] = useState('')
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [syncStopped, setSyncStopped] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)
  const requestRef = useRef<{ question: string; id: string } | null>(null)
  const conversationRef = useRef<HTMLDivElement>(null)
  const activeTurn = turns.find((turn) => activeStatuses.has(turn.status))

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
      .finally(() => { if (live) setLoading(false) })
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
      const next = [{ id, title: 'New conversation' }, ...saved]
      saveConversations(next)
      setSaved(next)
      setTurns([])
      setLoading(true)
      setSelectedId(id)
      setDraft('')
      setConfirmDelete(false)
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
      const next = saved.map((item) => item.id === selectedId && item.title === 'New conversation'
        ? { ...item, title: question.slice(0, 48) } : item)
      saveConversations(next)
      setSaved(next)
      setDraft('')
      requestRef.current = null
    } catch (reason) {
      setError(`Question was not accepted: ${reason instanceof Error ? reason.message : 'Unknown error.'} Retry will use the same request ID.`)
      if (reason instanceof AgentApiError && reason.status === 409) setReloadKey((key) => key + 1)
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
      const next = saved.filter((item) => item.id !== selectedId)
      saveConversations(next)
      setSaved(next)
      setSelectedId(next[0]?.id ?? '')
      setLoading(Boolean(next[0]?.id))
      setTurns([])
      setConfirmDelete(false)
    } catch (reason) { setError(`Could not delete this conversation: ${reason instanceof Error ? reason.message : 'Unknown error.'}`) }
    finally { setActing(false) }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') event.currentTarget.form?.requestSubmit()
  }

  return <section className="agent-section" aria-labelledby="agent-heading">
    <div className="agent-header"><div><h2 id="agent-heading">Research conversation</h2><p>Research questions over retained market observations.</p></div><Badge variant="outline" className="agent-mode">{agentMode === 'fixture' ? 'SYNTHETIC AGENT DEMO' : 'AGENT API'}</Badge></div>
    <div className="agent-toolbar"><label htmlFor="conversation-select">Conversation</label><select id="conversation-select" value={selectedId} onChange={(event) => { setTurns([]); setLoading(true); setSelectedId(event.target.value); setConfirmDelete(false); setDraft('') }} disabled={!saved.length || acting}>{saved.length ? saved.map((item) => <option key={item.id} value={item.id}>{item.title}</option>) : <option value="">No conversation yet</option>}</select><Button type="button" variant="outline" size="sm" disabled={acting} onClick={createConversation}><Plus size={15} aria-hidden="true" />New</Button>{selectedId && <Button type="button" variant="ghost" size="sm" className="agent-delete" disabled={acting} onClick={() => setConfirmDelete(true)}><Trash2 size={15} aria-hidden="true" />Delete</Button>}<span>Recent on this device</span></div>
    {confirmDelete && <div className="agent-delete-confirm" role="group" aria-label="Confirm conversation deletion"><p><strong>Delete this conversation permanently?</strong> Its turns and evidence cannot be recovered. The initial deployment has no backup.</p><div><Button type="button" size="sm" variant="destructive" disabled={acting} onClick={removeConversation}>Delete permanently</Button><Button type="button" size="sm" variant="ghost" onClick={() => setConfirmDelete(false)}>Keep conversation</Button></div></div>}
    {error && <div className="agent-error" role="alert"><p>{error}</p>{selectedId && <Button type="button" size="sm" variant="outline" onClick={() => { setSyncStopped(false); setReloadKey((key) => key + 1) }}><RotateCcw size={14} aria-hidden="true" />Reconnect</Button>}</div>}
    <div className="agent-conversation" ref={conversationRef} aria-live="polite">{loading ? <p className="agent-empty">Loading conversation…</p> : turns.length ? turns.map((turn) => <TurnCard turn={turn} key={turn.turn_id} />) : <div className="agent-empty"><strong>{selectedId ? 'Start with a research question' : 'Start a conversation'}</strong><p>{selectedId ? 'Questions and follow-ups in this conversation share context.' : 'Create a conversation to ask the research agent. New conversations start fresh.'}</p></div>}</div>
    {activeTurn && <div className="agent-active-actions"><span>{activeTurn.status === 'cancel_requested' ? 'Cancellation requested' : 'One turn is active in this conversation'}</span><Button type="button" size="sm" variant="outline" disabled={acting || activeTurn.status === 'cancel_requested'} onClick={cancel}><CircleStop size={15} aria-hidden="true" />Cancel turn</Button></div>}
    <form className="agent-composer" onSubmit={submit}><label htmlFor="agent-question">{turns.length ? 'Follow-up question' : 'Research question'}</label><div><Textarea id="agent-question" value={draft} onChange={(event) => { setDraft(event.target.value); if (requestRef.current?.question !== event.target.value.trim()) requestRef.current = null }} onKeyDown={handleKeyDown} maxLength={4000} rows={2} placeholder={agentMode === 'fixture' ? 'Use the documented sample question below' : 'Ask about returns, breadth, volume, or coverage'} disabled={!selectedId || Boolean(activeTurn) || acting} /><Button type="submit" disabled={!selectedId || !draft.trim() || Boolean(activeTurn) || acting}><ArrowUp size={16} aria-hidden="true" />Ask</Button></div><div className="agent-composer-foot"><span>{agentMode === 'fixture' ? 'Local fixture: example and one follow-up only. No model is called.' : 'Answers use validated, read-only calculations.'}</span><span>{draft.length} / 4000 · Ctrl+Enter to send</span></div></form>
    <div className="agent-suggestions"><span>Try</span><button type="button" disabled={!selectedId || Boolean(activeTurn)} onClick={() => setDraft(exampleQuestion)}>Gain + dollar volume last month</button>{turns.some((turn) => turn.status === 'completed') && <button type="button" disabled={!selectedId || Boolean(activeTurn)} onClick={() => setDraft(followUpQuestion)}>Ask a follow-up</button>}</div>
  </section>
}
