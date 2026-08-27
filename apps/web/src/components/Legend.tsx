import { ChevronDown, ListFilter } from 'lucide-react'

export function Legend() {
  return (
    <details className="legend-disclosure">
      <summary><ListFilter size={14} aria-hidden="true" />Map key<ChevronDown size={14} className="disclosure__chevron" /></summary>
      <div className="map-legend">
        <span><i className="legend-line road" />Street network</span>
        <span><i className="legend-line protected" />Protected corridor</span>
        <span><i className="legend-filter candidate" />Candidate</span>
        <span><i className="legend-filter selected" />Selected filter</span>
        <span><i className="legend-line counterexample" />Surviving route</span>
        <span><i className="legend-dot access" />Address access</span>
        <span><i className="legend-line component" />Mutual car-reachability region</span>
      </div>
    </details>
  )
}
