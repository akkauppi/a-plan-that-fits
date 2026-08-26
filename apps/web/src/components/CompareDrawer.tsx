import { ArrowRight, Check, X } from 'lucide-react'
import type { Alternative, Candidate } from '../types'

interface CompareDrawerProps {
  alternatives: Alternative[]
  candidates: Candidate[]
  activeId: string
  compareId?: string
  onActivate: (id: string) => void
  onCompare: (id?: string) => void
  onClose: () => void
}

export function CompareDrawer({ alternatives, candidates, activeId, compareId, onActivate, onCompare, onClose }: CompareDrawerProps) {
  return (
    <aside className="compare-drawer" aria-labelledby="compare-title">
      <div className="compare-drawer__head">
        <div><span>Equal-objective alternatives</span><h2 id="compare-title">Compare structures</h2></div>
        <button type="button" className="icon-button" onClick={onClose} aria-label="Close comparison"><X size={18} /></button>
      </div>
      <p>Orange is the active plan. Choose one alternative to overlay in teal; both share the same objective values.</p>
      <div className="alternative-list">
        {alternatives.map((alternative, index) => {
          const selected = alternative.id === activeId
          const compared = alternative.id === compareId
          return (
            <article key={alternative.id} className={`${selected ? 'is-active' : ''} ${compared ? 'is-compared' : ''}`}>
              <div className="alternative-title">
                <span>{String.fromCharCode(65 + index)}</span>
                <div><strong>{alternative.label}</strong><small>{alternative.result.selected_intervention_ids.length} modal filters · {alternative.result.iteration_count} iterations</small></div>
                {selected && <i><Check size={13} />active</i>}
              </div>
              <ol>
                {alternative.result.selected_intervention_ids.map((id) => <li key={id}>{candidates.find((candidate) => candidate.id === id)?.street_name ?? id}</li>)}
              </ol>
              <div className="alternative-actions">
                {!selected && <button type="button" onClick={() => onActivate(alternative.id)}>Use this plan <ArrowRight size={13} /></button>}
                {!selected && <button type="button" className={compared ? 'is-on' : ''} onClick={() => onCompare(compared ? undefined : alternative.id)}>{compared ? 'Hide overlay' : 'Overlay on map'}</button>}
              </div>
            </article>
          )
        })}
      </div>
      <div className="compare-key"><span><i className="orange" />Active plan</span><span><i className="teal" />Comparison plan</span></div>
    </aside>
  )
}
