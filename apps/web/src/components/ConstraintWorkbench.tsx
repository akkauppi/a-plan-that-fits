import { useMemo, useState } from 'react'
import {
  ArrowRight,
  Braces,
  CheckCircle2,
  ChevronRight,
  CircleDot,
  GitBranch,
  Map,
  Network,
  RotateCcw,
  Route,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
} from 'lucide-react'
import './ConstraintWorkbench.css'

export interface ConstraintFeatureRef {
  id: string
  name?: string
}

export interface ConstraintTraceEvent {
  id?: string
  type:
    | 'started'
    | 'candidate'
    | 'candidate_found'
    | 'counterexample'
    | 'counterexample_found'
    | 'clause_added'
    | 'refining'
    | 'rejected'
    | 'candidate_rejected'
    | 'verification'
    | 'verified'
    | 'verified_sat'
    | 'verified_optimal'
    | 'unsat'
    | 'verified_unsat'
    | 'timeout'
    | 'error'
    | string
  iteration?: number
  message?: string
  /** Boolean decisions proposed by Z3 in this iteration. */
  selectedDecisionIds?: string[]
  /** Unavailable edge IDs on a route or reachable-frontier cut returned by NetworkX. */
  witnessEdgeIds?: string[]
  /** Decision IDs in the clause actually added to Z3. */
  learnedClauseIds?: string[]
  /** Server-rendered constraint text, when available. */
  constraint?: string
  originId?: string
  destinationId?: string
}

export interface ConstraintWorkbenchResult {
  status: string
  selectedDecisionIds?: string[]
  verifiedOriginIds?: string[]
  unservedOriginIds?: string[]
  explanation?: string
}

export interface ConstraintWorkbenchProps {
  scenarioLabel?: string
  budget: number
  hazardClosureCount: number
  roadworksClosureCount: number
  origins: ConstraintFeatureRef[]
  destinations: ConstraintFeatureRef[]
  /** Exposed or disrupted links which the model may treat as contingency decisions. */
  decisionLinks: ConstraintFeatureRef[]
  events: ConstraintTraceEvent[]
  result?: ConstraintWorkbenchResult | null
  hazardLayerLabel?: string
  className?: string
}

type StageId = 'facts' | 'graph' | 'z3' | 'verify' | 'proof'

interface Stage {
  id: StageId
  eyebrow: string
  title: string
  icon: typeof Map
}

const STAGES: Stage[] = [
  { id: 'facts', eyebrow: '01', title: 'Map facts', icon: Map },
  { id: 'graph', eyebrow: '02', title: 'Graph rules', icon: Network },
  { id: 'z3', eyebrow: '03', title: 'Z3 proposes', icon: Braces },
  { id: 'verify', eyebrow: '04', title: 'Domain graph checks', icon: Route },
  { id: 'proof', eyebrow: '05', title: 'Checked result', icon: ShieldCheck },
]

const eventStage = (type: string): StageId => {
  if (type.includes('counterexample') || type.includes('verification')) return 'verify'
  if (type.includes('verified') || type === 'unsat' || type === 'timeout' || type === 'error') return 'proof'
  if (type.includes('candidate') || type === 'started' || type === 'refining' || type === 'clause_added') return 'z3'
  return 'graph'
}

const eventLabel = (event: ConstraintTraceEvent): string => {
  if (event.message) return event.message
  if (event.type.includes('candidate')) return 'Z3 proposed a set of contingency links.'
  if (event.type.includes('counterexample')) return 'NetworkX found an origin that still lacks access.'
  if (event.type === 'clause_added' || event.type === 'refining') return 'A graph-derived cut clause was added.'
  if (event.type.includes('verified')) return 'The fresh graph check passed.'
  if (event.type.includes('unsat')) return 'No decision set satisfies the current hard constraints.'
  if (event.type === 'timeout') return 'The solve stopped at its time limit; this is not UNSAT.'
  if (event.type === 'error') return 'Verification stopped because of a data or processing error.'
  return 'The analysis state changed.'
}

const shortId = (id: string): string => id.length > 28 ? `${id.slice(0, 13)}…${id.slice(-8)}` : id

const quoted = (id: string): string => `"${id}"`

const joinOr = (ids: string[]): string => ids.map((id) => `passable[${quoted(id)}]`).join('  ∨  ')

function referenceName(id: string | undefined, references: ConstraintFeatureRef[], fallback: string): string {
  if (!id) return fallback
  const match = references.find((item) => item.id === id)
  return match?.name ? `${match.name} (${id})` : id
}

export function ConstraintWorkbench({
  scenarioLabel = 'Current access scenario',
  budget,
  hazardClosureCount,
  roadworksClosureCount,
  origins,
  destinations,
  decisionLinks,
  events,
  result,
  hazardLayerLabel = 'flood-exposure scenario',
  className = '',
}: ConstraintWorkbenchProps) {
  const [activeStage, setActiveStage] = useState<StageId>('facts')
  const [eventCursor, setEventCursor] = useState<number | 'live'>('live')
  const [view, setView] = useState<'trace' | 'reuse'>('trace')

  const activeEvent = eventCursor === 'live'
    ? events.at(-1)
    : events[eventCursor]

  const namedRefs = useMemo(
    () => [...origins, ...destinations, ...decisionLinks],
    [origins, destinations, decisionLinks],
  )

  const candidateIds = activeEvent?.selectedDecisionIds
    ?? result?.selectedDecisionIds
    ?? []
  const learnedIds = activeEvent?.learnedClauseIds
    ?? activeEvent?.witnessEdgeIds
    ?? decisionLinks.slice(0, 3).map((item) => item.id)
  const sampleLink = decisionLinks[0]
  const sampleOrigin = origins[0]
  const sampleDestination = destinations[0]
  const learnedClauseIsLive = Boolean(activeEvent?.constraint || activeEvent?.learnedClauseIds?.length)

  const chooseEvent = (index: number) => {
    const event = events[index]
    setEventCursor(index)
    if (event) setActiveStage(eventStage(event.type))
    setView('trace')
  }

  return (
    <section className={`constraint-workbench ${className}`.trim()} aria-labelledby="constraint-workbench-title">
      <header className="constraint-workbench__header">
        <div>
          <span className="constraint-workbench__kicker">Constraint workbench</span>
          <h2 id="constraint-workbench-title">From spatial evidence to a checked answer</h2>
          <p>{scenarioLabel}</p>
        </div>
        <div className="constraint-workbench__view-switch" role="group" aria-label="Workbench view">
          <button type="button" className={view === 'trace' ? 'is-active' : ''} onClick={() => setView('trace')}>Live trace</button>
          <button type="button" className={view === 'reuse' ? 'is-active' : ''} onClick={() => setView('reuse')}>Other questions</button>
        </div>
      </header>

      {view === 'trace' ? (
        <>
          <div className="constraint-workbench__distinction">
            <GitBranch size={19} aria-hidden="true" />
            <p><strong>Two jobs, two engines.</strong> NetworkX measures vulnerability by removing explicitly unavailable links and checking reachability. Z3 enters only when we ask a choice question: which limited set of continuity commitments may be assumed passable?</p>
          </div>

          <nav className="constraint-pipeline" aria-label="Analysis stages">
            {STAGES.map((stage, index) => {
              const Icon = stage.icon
              return (
                <div className="constraint-pipeline__step" key={stage.id}>
                  <button
                    type="button"
                    aria-pressed={activeStage === stage.id}
                    className={activeStage === stage.id ? 'is-active' : ''}
                    onClick={() => setActiveStage(stage.id)}
                  >
                    <span>{stage.eyebrow}</span>
                    <Icon size={18} aria-hidden="true" />
                    <strong>{stage.title}</strong>
                  </button>
                  {index < STAGES.length - 1 && <ChevronRight size={15} aria-hidden="true" />}
                </div>
              )
            })}
          </nav>

          <div className="constraint-workbench__body">
            <div className="constraint-stage" aria-live="polite">
              <StageContent
                stage={activeStage}
                budget={budget}
                hazardClosureCount={hazardClosureCount}
                roadworksClosureCount={roadworksClosureCount}
                origins={origins}
                destinations={destinations}
                decisionLinks={decisionLinks}
                hazardLayerLabel={hazardLayerLabel}
                sampleLink={sampleLink}
                sampleOrigin={sampleOrigin}
                sampleDestination={sampleDestination}
                candidateIds={candidateIds}
                learnedIds={learnedIds}
                learnedClauseIsLive={learnedClauseIsLive}
                activeEvent={activeEvent}
                result={result}
                namedRefs={namedRefs}
              />
            </div>

            <aside className="constraint-trace" aria-label="Iteration trace">
              <div className="constraint-trace__head">
                <div><span>Iteration trace</span><strong>{events.length ? `${events.length} events` : 'Ready to run'}</strong></div>
                {eventCursor !== 'live' && (
                  <button type="button" onClick={() => setEventCursor('live')}><RotateCcw size={13} />Follow latest</button>
                )}
              </div>
              {events.length ? (
                <ol>
                  {events.slice(-6).map((event, visibleIndex) => {
                    const index = Math.max(0, events.length - 6) + visibleIndex
                    const isSelected = eventCursor === index || (eventCursor === 'live' && index === events.length - 1)
                    return (
                      <li key={event.id ?? `${event.type}-${event.iteration ?? index}-${index}`}>
                        <button type="button" className={isSelected ? 'is-selected' : ''} onClick={() => chooseEvent(index)}>
                          <span className={`constraint-trace__dot stage-${eventStage(event.type)}`} aria-hidden="true" />
                          <span><small>{event.iteration != null ? `Iteration ${event.iteration}` : 'Analysis'}</small><strong>{eventLabel(event)}</strong></span>
                        </button>
                      </li>
                    )
                  })}
                </ol>
              ) : (
                <div className="constraint-trace__empty">
                  <CircleDot size={19} aria-hidden="true" />
                  <p>Run the analysis to see Z3 proposals, graph findings, learned clauses and the fresh final check here.</p>
                </div>
              )}
            </aside>
          </div>

          <div className="constraint-workbench__caution">
            <TriangleAlert size={17} aria-hidden="true" />
            <p><strong>A true Boolean is an analytical assumption, not a field finding.</strong> <code>passable[c] = true</code> means the model may treat continuity zone <em>c</em> as passable under a stated contingency. Engineering, depth, velocity, legal and operational evidence must still justify that assumption.</p>
          </div>
        </>
      ) : (
        <ReusePatterns />
      )}
    </section>
  )
}

interface StageContentProps {
  stage: StageId
  budget: number
  hazardClosureCount: number
  roadworksClosureCount: number
  origins: ConstraintFeatureRef[]
  destinations: ConstraintFeatureRef[]
  decisionLinks: ConstraintFeatureRef[]
  hazardLayerLabel: string
  sampleLink?: ConstraintFeatureRef
  sampleOrigin?: ConstraintFeatureRef
  sampleDestination?: ConstraintFeatureRef
  candidateIds: string[]
  learnedIds: string[]
  learnedClauseIsLive: boolean
  activeEvent?: ConstraintTraceEvent
  result?: ConstraintWorkbenchResult | null
  namedRefs: ConstraintFeatureRef[]
}

function StageContent({
  stage,
  budget,
  hazardClosureCount,
  roadworksClosureCount,
  origins,
  destinations,
  decisionLinks,
  hazardLayerLabel,
  sampleLink,
  sampleOrigin,
  sampleDestination,
  candidateIds,
  learnedIds,
  learnedClauseIsLive,
  activeEvent,
  result,
  namedRefs,
}: StageContentProps) {
  if (stage === 'facts') {
    return (
      <>
        <StageHeading number="01" title="Begin with reviewable map facts" copy="The GIS pipeline fixes geometry, mode and scenario semantics before an optimizer is allowed to choose anything." />
        <div className="constraint-metrics">
          <Metric value={hazardClosureCount} label="car links unavailable by stress rule" />
          <Metric value={roadworksClosureCount} label="declared works closures" />
          <Metric value={origins.length} label="access origins" />
          <Metric value={destinations.length} label="permitted destinations" />
        </div>
        <CodeCard label="Graph predicate made from GIS evidence">
          <code>unavailable(e) := declared_works(e) ∨ (stress_enabled ∧ exposed(e, {quoted(hazardLayerLabel)}))</code>
        </CodeCard>
        <p className="constraint-stage__note">Exposure is kept separate from closure. The explicit stress-test switch makes {hazardClosureCount.toLocaleString('en')} private-car links unavailable in this run; mapped overlap alone never silently decides passability.</p>
      </>
    )
  }

  if (stage === 'graph') {
    return (
      <>
        <StageHeading number="02" title="Turn features into graph predicates" copy="Street geometries become directed edges. Snapped origins and destinations become nodes. Stable IDs keep every claim traceable back to a feature." />
        <div className="constraint-relation">
          <ReferencePill label="Origin" value={sampleOrigin?.name ?? sampleOrigin?.id ?? 'No origin selected'} />
          <ArrowRight size={18} aria-hidden="true" />
          <ReferencePill label="Directed graph" value={`G − ${hazardClosureCount + roadworksClosureCount} unavailable links`} />
          <ArrowRight size={18} aria-hidden="true" />
          <ReferencePill label="Destination" value={sampleDestination?.name ?? sampleDestination?.id ?? 'No destination selected'} />
        </div>
        <CodeCard label="Vulnerability question — evaluated directly by NetworkX">
          <code>reachable(G_available, {quoted(sampleOrigin?.id ?? 'origin_id')}, {quoted(sampleDestination?.id ?? 'destination_id')})</code>
        </CodeCard>
        <p className="constraint-stage__note"><strong>No Z3 is needed for this yes/no measurement.</strong> The constraint solver becomes useful when there are many allowed choices, a budget, and competing hard requirements.</p>
      </>
    )
  }

  if (stage === 'z3') {
    const candidateText = candidateIds.length
      ? candidateIds.map((id) => referenceName(id, decisionLinks, shortId(id))).join(' · ')
      : 'No candidate has been proposed yet.'
    return (
      <>
        <StageHeading number="03" title="Z3 chooses Booleans, not routes" copy="One Boolean represents one map-visible continuity zone. Hard constraints define the allowable combinations; Z3 does not initially know the complete reachability relation." />
        <CodeCard label="Decision variable">
          <code>passable[{quoted(sampleLink?.id ?? 'continuity_zone_id')}] ∈ {'{false, true}'}</code>
        </CodeCard>
        <CodeCard label="Current hard constraints">
          <code>Σ If(passable[c], 1, 0) ≤ {budget}</code>
          <code>members(c) ∩ fixed_roadworks = ∅</code>
          <code>for each learned frontier F: ∨ passable[c ∈ F]</code>
        </CodeCard>
        <div className="constraint-candidate">
          <Sparkles size={18} aria-hidden="true" />
          <div><span>Candidate assignment</span><strong>{candidateText}</strong></div>
        </div>
        <p className="constraint-stage__note">There are {decisionLinks.length.toLocaleString('en')} possible continuity zones. “Every required origin reaches at least one selected destination” is a domain requirement checked on the directed graph. A failed check is compiled into the next sound frontier clause.</p>
      </>
    )
  }

  if (stage === 'verify') {
    const origin = referenceName(activeEvent?.originId, origins, sampleOrigin?.name ?? 'selected origin')
    const destination = referenceName(activeEvent?.destinationId, destinations, sampleDestination?.name ?? 'permitted destination')
    return (
      <>
        <StageHeading number="04" title="The graph finds what the compact model missed" copy="The proposed assignment is applied to a fresh directed graph. A stranded origin produces a reachable set and its outgoing decision frontier. The least-disrupted route is shown only as a diagnosis." />
        <div className="constraint-witness">
          <div><span>Graph check</span><strong>{origin}</strong></div>
          <ArrowRight size={18} aria-hidden="true" />
          <div><span>Must reach</span><strong>{destination}</strong></div>
        </div>
        <CodeCard label={learnedClauseIsLive ? 'Clause added in the selected iteration' : 'Clause shape — not asserted until the verifier returns this cut'} tone={learnedClauseIsLive ? 'coral' : 'muted'}>
          <code>{activeEvent?.constraint ?? (learnedIds.length ? joinOr(learnedIds) : 'passable[zone_a] ∨ passable[zone_b]')}</code>
        </CodeCard>
        <p className="constraint-stage__note">The disjunction says at least one eligible continuity zone on the directed frontier must be assumed passable. The magenta least-disrupted route helps explain the failure, but it is not the clause. Z3 proposes again; the graph checker checks again.</p>
        {learnedClauseIsLive && learnedIds.length === 1 && (
          <p className="constraint-stage__note"><strong>This frontier has one eligible zone, so this step forces that Boolean.</strong> The teaching preset makes constraint compilation easy to inspect; richer trade-offs appear when several frontier zones, origins, schedules, costs, modes, or incompatibilities compete.</p>
        )}
      </>
    )
  }

  const verifiedCount = result?.verifiedOriginIds?.length ?? 0
  const unservedCount = result?.unservedOriginIds?.length ?? 0
  const resultStatus = result?.status ?? 'Not run'
  return (
    <>
      <StageHeading number="05" title="Rebuild and verify independently" copy="A candidate is never presented as final. The service rebuilds the available graph from frozen inputs, reapplies the returned decisions and checks every origin again." />
      <div className="constraint-proof">
        <CheckCircle2 size={23} aria-hidden="true" />
        <div>
          <span>Current result</span>
          <strong>{resultStatus}</strong>
          <p>{result?.explanation ?? 'The independent check will report here after a solve.'}</p>
        </div>
      </div>
      <div className="constraint-metrics constraint-metrics--proof">
        <Metric value={verifiedCount} label="origins verified" />
        <Metric value={unservedCount} label="origins still unserved" />
        <Metric value={result?.selectedDecisionIds?.length ?? 0} label="selected commitments" />
      </div>
      <CodeCard label="Claim boundary">
        <code>verified := all_required_reachability_checks_pass ∧ decisions_respect_budget</code>
      </CodeCard>
      <p className="constraint-stage__note">“Verified” only describes this graph, these closures, these origins and these permitted destinations. It is not a forecast of flood behaviour or proof that a road remains physically operable.</p>
      {namedRefs.length === 0 && <p className="constraint-stage__empty-note">Select origins, destinations and candidate links to generate a concrete trace.</p>}
    </>
  )
}

function StageHeading({ number, title, copy }: { number: string; title: string; copy: string }) {
  return (
    <header className="constraint-stage__heading">
      <span>{number}</span>
      <div><h3>{title}</h3><p>{copy}</p></div>
    </header>
  )
}

function Metric({ value, label }: { value: number; label: string }) {
  return <div className="constraint-metric"><strong>{value.toLocaleString('en')}</strong><span>{label}</span></div>
}

function ReferencePill({ label, value }: { label: string; value: string }) {
  return <div className="constraint-reference"><span>{label}</span><strong>{value}</strong></div>
}

function CodeCard({ children, label, tone = 'default' }: { children: React.ReactNode; label: string; tone?: 'default' | 'coral' | 'muted' }) {
  return (
    <div className={`constraint-code constraint-code--${tone}`}>
      <span>{label}</span>
      <div>{children}</div>
    </div>
  )
}

function ReusePatterns() {
  const patterns = [
    {
      title: 'Flood access',
      facts: 'Exposed links, reviewed closures, origins and designated network exits',
      choice: 'Which contingency links may remain or become passable?',
      check: 'Every required origin reaches a permitted destination',
    },
    {
      title: 'Roadworks scheduling',
      facts: 'Works extents, dates, dependencies and mode-specific closures',
      choice: 'Which works can occur in the same time window?',
      check: 'Access and protected corridors survive in every window',
    },
    {
      title: 'Evacuation',
      facts: 'Population origins, capacities, hazards and receiving sites',
      choice: 'Which sites, routes or phased departures are assigned?',
      check: 'Reachability, capacity and time constraints all hold',
    },
    {
      title: 'Service coverage',
      facts: 'Demand points, travel-time graph and facility candidates',
      choice: 'Which limited set of facilities is opened?',
      check: 'Every demand group is covered within the stated threshold',
    },
    {
      title: 'Network maintenance',
      facts: 'Asset condition, crew windows and critical connectivity',
      choice: 'Which assets are treated in each programme year?',
      check: 'Budgets, dependencies and minimum redundancy remain valid',
    },
  ]
  return (
    <div className="constraint-reuse">
      <div className="constraint-reuse__intro">
        <span>Reusable pattern</span>
        <h3>The geography changes; the reasoning loop stays recognisable.</h3>
        <p>Define observable spatial facts, expose a small set of defensible decisions, state hard requirements, let Z3 choose, and send each proposal back to the domain verifier. The verifier—not the optimizer—decides whether the spatial claim really holds.</p>
      </div>
      <div className="constraint-reuse__grid">
        {patterns.map((pattern, index) => (
          <article key={pattern.title}>
            <span>{String(index + 1).padStart(2, '0')}</span>
            <h4>{pattern.title}</h4>
            <dl>
              <div><dt>GIS facts</dt><dd>{pattern.facts}</dd></div>
              <div><dt>Solver chooses</dt><dd>{pattern.choice}</dd></div>
              <div><dt>Domain check</dt><dd>{pattern.check}</dd></div>
            </dl>
          </article>
        ))}
      </div>
      <div className="constraint-reuse__rule">
        <Braces size={20} aria-hidden="true" />
        <p><strong>Good constraint questions contain choices.</strong> If the question only asks “what is reachable after these closures?”, a graph algorithm is clearer. Use a constraint solver when budgets, assignments, timing, exclusions or alternative feasible combinations must be chosen together.</p>
      </div>
    </div>
  )
}
