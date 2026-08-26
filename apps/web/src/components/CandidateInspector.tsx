import { Ban, CircleOff, LockKeyholeOpen, X } from 'lucide-react'
import type { Candidate } from '../types'

interface CandidateInspectorProps {
  candidate: Candidate
  forced: boolean
  locked: boolean
  onForce: () => void
  onLock: () => void
  onClear: () => void
  onClose: () => void
  disabled?: boolean
}

export function CandidateInspector({ candidate, forced, locked, onForce, onLock, onClear, onClose, disabled = false }: CandidateInspectorProps) {
  return (
    <section className="candidate-inspector" aria-label={`Street constraints for ${candidate.street_name}`}>
      <div className="candidate-inspector__head">
        <div><span>Candidate street</span><strong>{candidate.street_name}</strong></div>
        <button type="button" className="icon-button" onClick={onClose} aria-label="Close street inspector"><X size={17} /></button>
      </div>
      {!candidate.eligible ? (
        <div className="ineligible-note"><Ban size={16} /><span><strong>Protected from selection</strong>{candidate.reason ?? 'This segment is not an eligible modal-filter location.'}</span></div>
      ) : (
        <div className="candidate-actions" role="group" aria-label="Street constraint">
          <button type="button" className={forced ? 'is-active force' : ''} onClick={onForce} disabled={disabled} aria-pressed={forced}>
            <CircleOff size={15} aria-hidden="true" /> Force filter
          </button>
          <button type="button" className={locked ? 'is-active lock' : ''} onClick={onLock} disabled={disabled} aria-pressed={locked}>
            <LockKeyholeOpen size={15} aria-hidden="true" /> Lock open
          </button>
          {(forced || locked) && <button type="button" onClick={onClear} disabled={disabled}>Clear</button>}
        </div>
      )}
      <p>Filters block private cars but preserve walking and cycling in this model.</p>
    </section>
  )
}
