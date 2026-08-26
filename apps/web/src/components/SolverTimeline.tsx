import { Check, CircleAlert, LoaderCircle, Route, ScanSearch, ShieldCheck, X } from 'lucide-react'
import type { SolveEvent, SolveStatus } from '../types'

const labelFor = (event: SolveEvent): string => {
  if (event.message) return event.message
  switch (event.type) {
    case 'started': return 'Solver started with the current assumptions.'
    case 'candidate_found': return 'Candidate intervention set proposed.'
    case 'counterexample_found': return 'A surviving private-car route was found.'
    case 'refining': return 'Added a route-cut constraint and solving again.'
    case 'candidate_rejected': return 'Candidate rejected to preserve local access.'
    case 'verified_sat': return 'All selected portal pairs are disconnected.'
    case 'verified_optimal': return 'Independent verification complete; objectives are optimal.'
    case 'verified_unsat': return 'The requested assumptions cannot be satisfied.'
    case 'timeout': return 'The configured solve time elapsed.'
    case 'cancelled': return 'Solve cancelled.'
    case 'data_error': return 'A data or verification error interrupted the solve.'
    case 'complete': return 'Solve complete.'
  }
}

const iconFor = (event: SolveEvent) => {
  switch (event.type) {
    case 'counterexample_found': return <Route size={14} />
    case 'candidate_found': return <ScanSearch size={14} />
    case 'verified_sat':
    case 'verified_optimal': return <ShieldCheck size={14} />
    case 'verified_unsat':
    case 'data_error': return <CircleAlert size={14} />
    case 'cancelled': return <X size={14} />
    case 'complete': return <Check size={14} />
    default: return <LoaderCircle size={14} />
  }
}

interface SolverTimelineProps {
  events: SolveEvent[]
  status: SolveStatus
}

export function SolverTimeline({ events, status }: SolverTimelineProps) {
  if (!events.length) return null
  return (
    <section className="solver-activity" aria-label="Solver activity" aria-live="polite">
      <div className="section-heading">
        <span>Proof activity</span>
        <small>{status === 'solving' || status === 'refining' || status === 'counterexample_found' || status === 'candidate_found' ? 'live' : `${events.length} events`}</small>
      </div>
      <ol className="solver-timeline">
        {events.slice(-7).map((event, index) => (
          <li key={`${event.type}-${event.iteration ?? index}-${index}`} className={`event-${event.type}`}>
            <span className="timeline-icon" aria-hidden="true">{iconFor(event)}</span>
            <span><strong>{labelFor(event)}</strong>{event.iteration != null && <small>Iteration {event.iteration}</small>}</span>
          </li>
        ))}
      </ol>
    </section>
  )
}
