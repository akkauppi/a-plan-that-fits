import { useEffect, useRef } from 'react'
import { AlertTriangle, BookOpenText, CheckCircle2, ExternalLink, X } from 'lucide-react'
import type { Scenario } from '../types'

interface MethodologyProps {
  scenario: Scenario
  onClose: () => void
}

export function Methodology({ scenario, onClose }: MethodologyProps) {
  const closeRef = useRef<HTMLButtonElement>(null)
  const boundarySetbackM = scenario.terminal_zone.properties.setback_m
  const portalSetbackM = scenario.portal_approach_zones.properties.setback_m

  useEffect(() => {
    closeRef.current?.focus()
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', closeOnEscape)
    return () => document.removeEventListener('keydown', closeOnEscape)
  }, [onClose])

  return (
    <aside className="method-sheet" id="methodology" role="dialog" aria-modal="true" aria-labelledby="method-title">
      <div className="method-sheet__head">
        <div><span>Methods & limits</span><h2 id="method-title">What the proof means</h2></div>
        <button ref={closeRef} type="button" className="icon-button" onClick={onClose} aria-label="Close methods panel"><X size={18} /></button>
      </div>
      <p className="method-lede">The modal-filter placement experiment tests network permeability. It is a demonstrator and research instrument—not an operational traffic plan.</p>

      <section>
        <h3><CheckCircle2 size={17} />What can be claimed</h3>
        <blockquote>Under the current graph, mode, candidate-intervention, and portal assumptions, no private-car route remains between the selected portal pairs.</blockquote>
      </section>

      <section>
        <h3><BookOpenText size={17} />Method in brief</h3>
        <ol>
          <li><span>01</span><p>Candidate filter marker midpoints within {boundarySetbackM} m of the study boundary or {portalSetbackM} m of any selectable portal crossing are excluded, removing immediate endpoint cuts from the search.</p></li>
          <li><span>02</span><p>Z3 proposes a set of eligible local-street filters under the budget and user constraints.</p></li>
          <li><span>03</span><p>NetworkX searches the directed car graph for a surviving route between every required portal pair.</p></li>
          <li><span>04</span><p>Each counterexample becomes a new cut constraint. Candidates that strand an address cluster are rejected.</p></li>
          <li><span>05</span><p>The final private-car graph and local car access are checked independently. The before/after map wash shows directed strong components: maximal regions with mutual private-car reachability, not traffic volumes. Walking and cycling passability, and removable emergency access, remain explicit filter assumptions rather than separate network proofs.</p></li>
        </ol>
      </section>

      <section>
        <h3>Balanced objective order</h3>
        <p className="objective-copy">The solver first minimizes intervention count, then weighted street cost, local-access risk, and finally adjacent-filter clustering. Each earlier value is fixed before the next is considered—there is no unexplained composite “city score.”</p>
      </section>

      <section className="limitations">
        <h3><AlertTriangle size={17} />Limitations</h3>
        <ul>
          <li>No prediction is made about traffic volumes, behaviour, or redistribution outside the boundary.</li>
          <li>OpenStreetMap tags can be incomplete; candidate eligibility is an abstraction, not a site-feasibility audit.</li>
          <li>Emergency access assumes removable or unlockable filters when that option is enabled. It is not legal approval.</li>
          <li>Walking, cycling, and emergency routes are not separately verified in this frozen scenario.</li>
          <li>The {boundarySetbackM} m boundary and {portalSetbackM} m portal-crossing setbacks are analytical endpoint-bias controls, not physical or legal siting rules.</li>
          <li>Address clusters approximate local private-car access; individual driveways and curb operations are not modelled.</li>
          <li>A planter is the interface symbol. A real treatment could instead be a bollard, gate, camera restriction, or closure.</li>
        </ul>
      </section>

      <section className="source-note">
        <span>Frozen source</span>
        <strong>{scenario.snapshot_id}</strong>
        <p>{scenario.name} · {formatTimestamp(scenario.snapshot_timestamp)}</p>
        <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap contributors · ODbL <ExternalLink size={12} /></a>
      </section>
    </aside>
  )
}

function formatTimestamp(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' }).format(date) + ' UTC'
}
