import { AlertTriangle, ArrowUpRight, Check, ChevronRight, Clock3, Copy, MapPinned, ShieldCheck, Sparkles } from 'lucide-react'
import type { Candidate, SolveResult, SolveStatus, SuggestedRelaxation } from '../types'

const isVerified = (status: string, result: SolveResult) =>
  (status === 'verified_sat' || status === 'verified_optimal') && result.verification_status === 'independently_verified'
const isUnsat = (status: string) => status === 'verified_unsat'

interface ResultPanelProps {
  result: SolveResult
  status: SolveStatus
  candidates: Candidate[]
  onSelectCandidate: (candidate: Candidate) => void
  onNext: () => void
  onCompare: () => void
  onRaiseBudget: (budget?: number) => void
  onUnlock: (candidateId: string) => void
  onReleaseForced: (candidateId: string) => void
  onRemovePortalPair: (pair: { a: string; b: string }) => void
  onReviewAssumptions: () => void
  onOpenMethod: () => void
  canUnlock: boolean
  alternativeCount: number
  nextPending: boolean
}

export function ResultPanel({
  result,
  status,
  candidates,
  onSelectCandidate,
  onNext,
  onCompare,
  onRaiseBudget,
  onUnlock,
  onReleaseForced,
  onRemovePortalPair,
  onReviewAssumptions,
  onOpenMethod,
  canUnlock,
  alternativeCount,
  nextPending,
}: ResultPanelProps) {
  if (isVerified(status, result)) {
    const access = result.address_access_summary ?? {}
    const served = Number(access.served ?? (access.all_accessible ? access.total : 0) ?? 0)
    const total = Number(access.total ?? served)
    return (
      <section className="result-panel result-panel--verified" aria-label="Verified solution" role="status">
        <div className="result-status">
          <span className="result-status__icon"><ShieldCheck size={22} /></span>
          <div><span>Verified under this model</span><h2>{result.selected_intervention_ids.length} filters cut the selected routes</h2></div>
        </div>
        <p>{result.explanation || 'No private-car path remains between the selected portal pairs, and the final network has been independently checked.'}</p>
        <div className="proof-metrics">
          <div><strong>{result.selected_intervention_ids.length}</strong><span>interventions</span></div>
          <div><strong>{total ? `${served}/${total}` : 'All'}</strong><span>clusters served</span></div>
          <div><strong>{result.iteration_count}</strong><span>refinements</span></div>
          <div><strong>{formatDuration(result.timing_ms)}</strong><span>solve time</span></div>
        </div>
        <details className="objective-vector">
          <summary>Inspect objective vector and access detours</summary>
          <dl>
            {Object.entries(result.objective_values).map(([key, value]) => value != null && (
              <div key={key}><dt>{humanize(key)}</dt><dd>{String(value)}</dd></div>
            ))}
            {result.local_detour_metrics.mean_additional_distance_m != null && (
              <div><dt>Mean access detour</dt><dd>{String(result.local_detour_metrics.mean_additional_distance_m)} m</dd></div>
            )}
            {result.local_detour_metrics.maximum_additional_distance_m != null && (
              <div><dt>Maximum access detour</dt><dd>{String(result.local_detour_metrics.maximum_additional_distance_m)} m</dd></div>
            )}
          </dl>
          <p>Objectives are minimized lexicographically; later values never trade away an earlier priority.</p>
        </details>
        <div className="selected-list">
          <span className="selected-list__label">Selected modal filters</span>
          {result.selected_intervention_ids.map((id, index) => {
            const candidate = candidates.find((item) => item.id === id)
            return (
              <button key={id} type="button" onClick={() => candidate && onSelectCandidate(candidate)} disabled={!candidate}>
                <span className="filter-glyph" aria-hidden="true"><i /><i /><i /></span>
                <span><strong>{candidate?.street_name ?? id}</strong><small>Filter {index + 1} · private cars blocked</small></span>
                <MapPinned size={15} aria-hidden="true" />
              </button>
            )
          })}
        </div>
        <div className="result-actions">
          <button type="button" className="secondary-action" onClick={onNext} disabled={nextPending}>
            {nextPending ? <Clock3 className="spin" size={16} /> : <Sparkles size={16} />} {nextPending ? 'Searching…' : 'Next solution'}
          </button>
          <button type="button" className="secondary-action" onClick={onCompare} disabled={alternativeCount < 2}>
            <Copy size={16} /> Compare <span className="button-count">{alternativeCount}</span>
          </button>
        </div>
        <small className="proof-statement">Proof scope: current graph, candidates, portal pairs, mode rules, and OSM snapshot only.</small>
      </section>
    )
  }

  if (isUnsat(status)) {
    return (
      <section className="result-panel result-panel--unsat" aria-label="Verified infeasible result" role="alert">
        <div className="result-status">
          <span className="result-status__icon"><AlertTriangle size={21} /></span>
          <div><span>Verified infeasible</span><h2>These assumptions conflict</h2></div>
        </div>
        <p>{result.explanation || 'No eligible intervention set satisfies the selected route cuts and local-access requirements within this budget.'}</p>
        {!!result.unsat_core?.length && (
          <div className="unsat-core">
            <span>Small conflicting set</span>
            <ul>{result.unsat_core.map((item) => <li key={item}><Check size={12} />{humanize(item)}</li>)}</ul>
          </div>
        )}
        <div className="relaxations">
          <span>Try one change — nothing is changed automatically</span>
          {result.suggested_relaxations?.length ? result.suggested_relaxations.map((suggestion, index) => {
            const item = typeof suggestion === 'string' ? { label: suggestion, type: '' } : suggestion
            return <button type="button" key={`${item.label}-${index}`} onClick={() => relaxationAction(item, { onRaiseBudget, onUnlock, onReleaseForced, onRemovePortalPair, onReviewAssumptions })}>{item.label}<ChevronRight size={15} /></button>
          }) : (
            <>
              <button type="button" onClick={() => onRaiseBudget()}>Increase budget by one <ChevronRight size={15} /></button>
              {canUnlock && <button type="button" onClick={onReviewAssumptions}>Review locked streets <ChevronRight size={15} /></button>}
            </>
          )}
        </div>
      </section>
    )
  }

  const title = status === 'timeout' ? 'Solve timed out' : status === 'cancelled' ? 'Solve cancelled' : 'Verification could not finish'
  return (
    <section className="result-panel result-panel--indeterminate" role="alert">
      <div className="result-status">
        <span className="result-status__icon"><Clock3 size={21} /></span>
        <div><span>Indeterminate — not UNSAT</span><h2>{title}</h2></div>
      </div>
      <p>{result.explanation || 'No claim about feasibility can be made from this run. Adjust the timeout or try again.'}</p>
      <button type="button" className="result-method-link" onClick={onOpenMethod}>
        Why this is different from infeasible <ArrowUpRight size={13} />
      </button>
    </section>
  )
}

function formatDuration(milliseconds: number): string {
  if (milliseconds < 1000) return `${Math.max(0, Math.round(milliseconds))}ms`
  return `${(milliseconds / 1000).toFixed(milliseconds > 10_000 ? 0 : 1)}s`
}

function humanize(value: string): string {
  return value.replace(/[_:-]+/g, ' ').replace(/^\w/, (letter) => letter.toUpperCase())
}

function relaxationAction(
  suggestion: SuggestedRelaxation,
  actions: {
    onRaiseBudget: (budget?: number) => void
    onUnlock: (candidateId: string) => void
    onReleaseForced: (candidateId: string) => void
    onRemovePortalPair: (pair: { a: string; b: string }) => void
    onReviewAssumptions: () => void
  },
): void {
  const type = suggestion.type ?? suggestion.action
  if (type === 'increase_budget') actions.onRaiseBudget(suggestion.value)
  else if ((type === 'unlock_candidate' || type === 'unlock_street') && suggestion.candidate_id) {
    actions.onUnlock(suggestion.candidate_id)
  } else if (type === 'release_forced_intervention' && suggestion.candidate_id) {
    actions.onReleaseForced(suggestion.candidate_id)
  } else if (type === 'remove_portal_pair' && suggestion.pair) {
    actions.onRemovePortalPair(suggestion.pair)
  } else actions.onReviewAssumptions()
}
