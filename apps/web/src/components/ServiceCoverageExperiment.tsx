import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Ban,
  Check,
  CircleStop,
  Database,
  Gauge,
  LoaderCircle,
  MapPinned,
  Minus,
  Plus,
  RotateCcw,
  Route,
  Scale,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
  UsersRound,
  X,
} from 'lucide-react'
import {
  cancelServiceCoverageSolve,
  getServiceCoverageScenario,
  ServiceCoverageApiError,
  streamServiceCoverageSolve,
} from './ServiceCoverageApi'
import { ServiceCoverageMap, type ServiceCoverageMapView } from './ServiceCoverageMap'
import type {
  ServiceCandidateSite,
  ServiceCoverageAttributionSource,
  ServiceCoverageResult,
  ServiceCoverageScenario,
  ServiceCoverageSolveEvent,
  ServiceCoverageSolveRequest,
  ServiceCoverageStatus,
  ServiceSiteConstraint,
} from './ServiceCoverageTypes'
import './ServiceCoverageExperiment.css'

type ExperimentStatus = 'idle' | 'solving' | ServiceCoverageStatus

export function ServiceCoverageExperiment({ active = true }: { active?: boolean }) {
  const [scenario, setScenario] = useState<ServiceCoverageScenario>()
  const [loadError, setLoadError] = useState<string>()
  const [reloadKey, setReloadKey] = useState(0)
  const [siteBudget, setSiteBudget] = useState(4)
  const [maxDistance, setMaxDistance] = useState(1200)
  const [capacityMultiplier, setCapacityMultiplier] = useState(1)
  const [timeoutSeconds, setTimeoutSeconds] = useState(30)
  const [forcedSiteIds, setForcedSiteIds] = useState<string[]>([])
  const [bannedSiteIds, setBannedSiteIds] = useState<string[]>([])
  const [events, setEvents] = useState<ServiceCoverageSolveEvent[]>([])
  const [result, setResult] = useState<ServiceCoverageResult>()
  const [status, setStatus] = useState<ExperimentStatus>('idle')
  const [runError, setRunError] = useState<string>()
  const [mapView, setMapView] = useState<ServiceCoverageMapView>('demand')
  const [inspectedSiteId, setInspectedSiteId] = useState<string>()
  const abortRef = useRef<AbortController | undefined>(undefined)
  const solveIdRef = useRef<string | undefined>(undefined)
  const terminalStatusRef = useRef<ExperimentStatus>('idle')

  const abortActiveSolve = useCallback(() => {
    const controller = abortRef.current
    const solveId = solveIdRef.current
    if (!controller && !solveId) return false
    // Start cooperative backend cancellation while the solve identifier is
    // still available, then invalidate the local run before aborting its stream.
    if (solveId) void cancelServiceCoverageSolve(solveId).catch(() => undefined)
    solveIdRef.current = undefined
    abortRef.current = undefined
    controller?.abort()
    return true
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    setLoadError(undefined)
    getServiceCoverageScenario(controller.signal)
      .then((loaded) => {
        setScenario(loaded)
        setSiteBudget(loaded.defaults.site_budget)
        setMaxDistance(loaded.defaults.max_distance_m)
        setCapacityMultiplier(loaded.defaults.capacity_multiplier)
        setTimeoutSeconds(loaded.defaults.timeout_seconds)
      })
      .catch((caught: unknown) => {
        if ((caught as Error).name !== 'AbortError') {
          setLoadError(caught instanceof ServiceCoverageApiError
            ? caught.message
            : 'The frozen service-coverage evidence could not be loaded.')
        }
      })
    return () => controller.abort()
  }, [reloadKey])

  useEffect(() => () => { abortActiveSolve() }, [abortActiveSolve])

  useEffect(() => {
    if (active || !abortRef.current) return
    abortActiveSolve()
    terminalStatusRef.current = 'cancelled'
    setStatus('cancelled')
    setRunError('The solve was cancelled when you left the experiment. No feasibility conclusion was reached.')
  }, [abortActiveSolve, active])

  const resetOutcome = useCallback(() => {
    abortActiveSolve()
    terminalStatusRef.current = 'idle'
    setEvents([])
    setResult(undefined)
    setStatus('idle')
    setRunError(undefined)
    setMapView('demand')
  }, [abortActiveSolve])

  const updateInput = useCallback((change: () => void) => {
    change()
    resetOutcome()
  }, [resetOutcome])

  const latestEvent = events.at(-1)
  const latestAssignmentEvent = [...events].reverse().find((event) => event.assignments?.length || event.result?.assignments.length)
  const visibleAssignments = latestEvent?.result?.assignments ?? latestAssignmentEvent?.assignments ?? latestAssignmentEvent?.result?.assignments ?? result?.assignments ?? []
  const visibleSiteIds = latestEvent?.result?.selected_site_ids ?? latestAssignmentEvent?.selected_site_ids ?? latestAssignmentEvent?.result?.selected_site_ids ?? result?.selected_site_ids ?? []
  const visibleLoads = latestEvent?.result?.site_loads ?? latestAssignmentEvent?.site_loads ?? latestAssignmentEvent?.result?.site_loads ?? result?.site_loads ?? []
  const witnessCellId = latestEvent?.witness_cell_id
    ?? (typeof result?.diagnostics?.witness_cell_id === 'string' ? result.diagnostics.witness_cell_id : undefined)
  const inspectedSite = scenario?.candidate_sites.find((site) => site.id === inspectedSiteId)
  const isSolving = status === 'solving'
  const totalPopulation = scenario?.population_cells.reduce((sum, cell) => sum + cell.population, 0) ?? 0

  const solve = useCallback(async () => {
    if (!scenario) return
    const controller = new AbortController()
    abortActiveSolve()
    abortRef.current = controller
    terminalStatusRef.current = 'solving'
    setStatus('solving')
    setEvents([])
    setResult(undefined)
    setRunError(undefined)
    setMapView('demand')
    setInspectedSiteId(undefined)
    const request: ServiceCoverageSolveRequest = {
      scenario_id: scenario.id,
      site_budget: siteBudget,
      max_distance_m: maxDistance,
      capacity_multiplier: capacityMultiplier,
      forced_site_ids: forcedSiteIds,
      banned_site_ids: bannedSiteIds,
      timeout_seconds: timeoutSeconds,
    }
    try {
      const final = await streamServiceCoverageSolve(request, (event) => {
        if (abortRef.current !== controller) return
        setEvents((current) => [...current, event])
        if (event.assignments?.length || event.result?.assignments.length) setMapView('assignment')
        const terminal = terminalStatus(event.type)
        if (terminal) {
          terminalStatusRef.current = terminal
          setStatus(terminal)
        }
        if (event.result) {
          setResult(event.result)
          terminalStatusRef.current = event.result.status
          setStatus(event.result.status)
          if (event.result.assignments.length) setMapView('assignment')
          else if (event.result.status === 'verified_unsat') setMapView('demand')
        }
      }, controller.signal, (solveId) => {
        if (abortRef.current === controller) solveIdRef.current = solveId
        else void cancelServiceCoverageSolve(solveId).catch(() => undefined)
      })
      if (abortRef.current !== controller) return
      if (final) {
        setResult(final)
        setStatus(final.status)
        terminalStatusRef.current = final.status
        if (final.assignments.length) setMapView('assignment')
        else if (final.status === 'verified_unsat') setMapView('demand')
      } else if (terminalStatusRef.current === 'solving') {
        terminalStatusRef.current = 'data_error'
        setStatus('data_error')
        setRunError('The solve stream ended before a verified result was returned.')
      }
    } catch (caught: unknown) {
      if (abortRef.current !== controller) return
      if ((caught as Error).name === 'AbortError') {
        terminalStatusRef.current = 'cancelled'
        setStatus('cancelled')
        setRunError('The solve was cancelled. No feasibility conclusion was reached.')
      } else {
        terminalStatusRef.current = 'data_error'
        setStatus('data_error')
        setRunError(caught instanceof ServiceCoverageApiError
          ? caught.message
          : 'The solver stream failed before fresh verification.')
      }
    } finally {
      if (abortRef.current === controller) {
        abortRef.current = undefined
        solveIdRef.current = undefined
      }
    }
  }, [abortActiveSolve, bannedSiteIds, capacityMultiplier, forcedSiteIds, maxDistance, scenario, siteBudget, timeoutSeconds])

  const cancel = useCallback(() => {
    if (!abortActiveSolve()) return
    terminalStatusRef.current = 'cancelled'
    setStatus('cancelled')
    setRunError('The solve was cancelled. No feasibility conclusion was reached.')
  }, [abortActiveSolve])

  const setConstraint = useCallback((site: ServiceCandidateSite, next: ServiceSiteConstraint) => {
    if (terminalStatusRef.current === 'solving') return
    updateInput(() => {
      setForcedSiteIds((current) => next === 'forced'
        ? Array.from(new Set([...current, site.id])).sort()
        : current.filter((id) => id !== site.id))
      setBannedSiteIds((current) => next === 'banned'
        ? Array.from(new Set([...current, site.id])).sort()
        : current.filter((id) => id !== site.id))
    })
  }, [updateInput])

  const resetAll = useCallback(() => {
    if (!scenario) return
    resetOutcome()
    setSiteBudget(scenario.defaults.site_budget)
    setMaxDistance(scenario.defaults.max_distance_m)
    setCapacityMultiplier(scenario.defaults.capacity_multiplier)
    setTimeoutSeconds(scenario.defaults.timeout_seconds)
    setForcedSiteIds([])
    setBannedSiteIds([])
    setInspectedSiteId(undefined)
  }, [resetOutcome, scenario])

  if (!scenario) {
    return (
      <main className="service-coverage-loading" aria-live="polite">
        {loadError ? (
          <div><TriangleAlert size={24} /><h1 data-page-heading tabIndex={-1}>Service-coverage evidence unavailable</h1><p>{loadError}</p><button type="button" onClick={() => setReloadKey((value) => value + 1)}>Retry frozen scenario</button></div>
        ) : (
          <div><LoaderCircle className="spin" size={24} /><h1 data-page-heading tabIndex={-1}>Loading frozen service evidence</h1><p>Population cells, candidate sites and walking network are being prepared.</p></div>
        )}
      </main>
    )
  }

  return (
    <main className="service-coverage-experiment" aria-labelledby="service-coverage-title">
      <section className="service-coverage-map-region" aria-label="Equitable service coverage analysis map">
        <ServiceCoverageMap
          scenario={scenario}
          assignments={visibleAssignments}
          selectedSiteIds={visibleSiteIds}
          siteLoads={visibleLoads}
          forcedSiteIds={forcedSiteIds}
          bannedSiteIds={bannedSiteIds}
          witnessCellId={witnessCellId}
          view={mapView}
          onViewChange={setMapView}
          onSiteSelect={isSolving ? undefined : (site) => setInspectedSiteId(site.id)}
          solving={isSolving}
          resultStatus={status === 'idle' || status === 'solving' ? undefined : status}
          iteration={latestEvent?.iteration}
          statusMessage={latestEvent?.message ?? result?.message}
        />

        {inspectedSite && (
          <SiteInspector
            site={inspectedSite}
            constraint={constraintFor(inspectedSite.id, forcedSiteIds, bannedSiteIds)}
            selected={visibleSiteIds.includes(inspectedSite.id)}
            load={visibleLoads.find((load) => load.site_id === inspectedSite.id)}
            capacityMultiplier={capacityMultiplier}
            disabled={isSolving}
            onConstraint={(next) => setConstraint(inspectedSite, next)}
            onClose={() => setInspectedSiteId(undefined)}
          />
        )}
      </section>

      <aside className="service-coverage-instrument" aria-label="Service-coverage solver controls">
        <div className="service-coverage-instrument__scroll">
          <header className="service-coverage-intro">
            <span><UsersRound size={14} /> Experiment 03 · service location</span>
            <h1 id="service-coverage-title" data-page-heading tabIndex={-1}>Equitable service coverage</h1>
            <p>Which reviewed sites can serve every included population cell within the stated walking distance and analytical capacity?</p>
            <dl>
              <div><dt>Demand</dt><dd>{Math.round(totalPopulation).toLocaleString('en')} people · {scenario.population_cells.length} cells</dd></div>
              <div><dt>Choices</dt><dd>{scenario.candidate_sites.filter((site) => site.eligible).length} eligible sites</dd></div>
            </dl>
          </header>

          <section className="coverage-control coverage-budget" aria-labelledby="coverage-budget-title">
            <header><span>01</span><div><h2 id="coverage-budget-title">Choose at most how many sites?</h2><p>Z3 may use fewer when every other hard rule still holds.</p></div></header>
            <div className="coverage-budget__value">
              <button type="button" onClick={() => updateInput(() => setSiteBudget((value) => Math.max(0, value - 1)))} disabled={isSolving || siteBudget <= 0} aria-label="Decrease site budget"><Minus size={16} /></button>
              <output aria-label={`At most ${siteBudget} selected sites`}><strong>{siteBudget}</strong><span>sites<br />maximum</span></output>
              <button type="button" onClick={() => updateInput(() => setSiteBudget((value) => Math.min(scenario.candidate_sites.length, value + 1)))} disabled={isSolving || siteBudget >= scenario.candidate_sites.length} aria-label="Increase site budget"><Plus size={16} /></button>
            </div>
            <input type="range" min="0" max={scenario.candidate_sites.length} value={siteBudget} onChange={(event) => updateInput(() => setSiteBudget(Number(event.target.value)))} disabled={isSolving} aria-label="Maximum selected-site budget" />
          </section>

          <section className="coverage-control" aria-labelledby="coverage-distance-title">
            <header><span>02</span><div><h2 id="coverage-distance-title">Set a walking-distance limit</h2><p>Network path plus two straight snap connectors—not travel time or a circular buffer.</p></div></header>
            <label className="coverage-distance">
              <span><Route size={15} /><strong>{maxDistance.toLocaleString('en')} m</strong><small>maximum assignment</small></span>
              <input type="range" min="400" max="2400" step="100" value={maxDistance} onChange={(event) => updateInput(() => setMaxDistance(Number(event.target.value)))} disabled={isSolving} aria-label="Maximum modelled walking distance in metres, including snap connectors" />
              <i><span>400 m</span><span>2,400 m</span></i>
            </label>
          </section>

          <section className="coverage-control" aria-labelledby="coverage-capacity-title">
            <header><span>03</span><div><h2 id="coverage-capacity-title">Test an analytical capacity</h2><p>Capacity is a declared sensitivity input—not measured staffing, floor area or actual service throughput.</p></div></header>
            <div className="coverage-capacity" role="group" aria-label="Analytical capacity multiplier">
              {[0.75, 1, 1.25].map((multiplier) => (
                <button type="button" key={multiplier} className={capacityMultiplier === multiplier ? 'is-active' : ''} aria-pressed={capacityMultiplier === multiplier} onClick={() => updateInput(() => setCapacityMultiplier(multiplier))} disabled={isSolving}>
                  <strong>{Math.round(multiplier * 100)}%</strong><small>{multiplier === 1 ? 'declared baseline' : 'sensitivity case'}</small>
                </button>
              ))}
            </div>
            <p className="coverage-assumption"><Gauge size={13} />Every included cell must be assigned once; selected sites may not exceed their multiplied capacity.</p>
          </section>

          <section className="coverage-site-constraints" aria-label="User site constraints">
            <button type="button" onClick={() => setInspectedSiteId(scenario.candidate_sites.find((site) => site.eligible)?.id)} disabled={isSolving}><MapPinned size={15} /><span><strong>Force or exclude candidate sites</strong><small>Choose on the map · {forcedSiteIds.length} forced · {bannedSiteIds.length} excluded</small></span><span aria-hidden="true">→</span></button>
          </section>

          <button type="button" className={`coverage-solve ${isSolving ? 'is-solving' : ''}`} onClick={isSolving ? cancel : solve}>
            <span>{isSolving ? <CircleStop size={18} /> : <Scale size={18} />}</span>
            <span><strong>{isSolving ? 'Cancel solve' : `Assign coverage with ${siteBudget}`}</strong><small>{isSolving ? 'Cancellation is indeterminate—not UNSAT' : 'Frozen walking matrix · Z3 assignment · fresh route check'}</small></span>
            {isSolving ? <LoaderCircle className="spin" size={17} /> : <span aria-hidden="true">→</span>}
          </button>

          <CoverageResult
            status={status}
            result={result}
            error={runError}
            scenario={scenario}
            budget={siteBudget}
            maxDistance={maxDistance}
            onRaiseBudget={() => updateInput(() => setSiteBudget((value) => Math.min(scenario.candidate_sites.length, value + 1)))}
            onRaiseDistance={() => updateInput(() => setMaxDistance((value) => Math.min(2400, value + 200)))}
            onRaiseCapacity={() => updateInput(() => setCapacityMultiplier(1.25))}
          />

          <CoverageSolveTrace events={events} />

          <details className="coverage-method">
            <summary><Sparkles size={15} /><span><strong>How GIS becomes constraints</strong><small>Direct assignment model · inspect the proof boundary</small></span><span aria-hidden="true">⌄</span></summary>
            <div>
              <ol>
                <li><b>GIS / NetworkX</b><span>Compile each frozen network path and its two straight snap connectors. Pairs beyond {maxDistance.toLocaleString('en')} total modelled metres become unavailable choices.</span></li>
                <li><b>Z3</b><span>Choose open sites and exactly one available assignment per cell while respecting budget and analytical capacity.</span></li>
                <li><b>Lexicographic objectives</b><span>Minimise site count, then worst distance, then population-weighted total distance, then selected-site load imbalance.</span></li>
                <li><b>Fresh verification</b><span>Recompute every returned walking route and independently check budget, eligibility, distance and capacity.</span></li>
              </ol>
              <p>Unlike the route-cut experiments, this slice does not need counterexample-guided path clauses: the complete finite cell–site matrix is frozen before Z3 solves, with unavailable relations constrained false.</p>
            </div>
          </details>

          <details className="coverage-method">
            <summary><Database size={15} /><span><strong>Assumptions, evidence & limits</strong><small>{timeoutSeconds}s timeout · frozen replay</small></span><span aria-hidden="true">⌄</span></summary>
            <div>
              <label>Solver timeout<select value={timeoutSeconds} onChange={(event) => updateInput(() => setTimeoutSeconds(Number(event.target.value)))} disabled={isSolving}>{[10, 30, 60, 120].map((seconds) => <option key={seconds} value={seconds}>{seconds} seconds</option>)}</select></label>
              <p><strong>What “verified” means:</strong> under this frozen walking graph, included population grid, candidate eligibility and declared capacity, every included cell has a checked route to its assigned site within the stated distance. It does not establish actual demand, accessibility, operating capacity, service quality, funding, safety or implementation feasibility.</p>
              <p>{scenario.methodology}</p>
            </div>
          </details>

          <footer className="coverage-footer">
            <button type="button" onClick={resetAll} disabled={isSolving}><RotateCcw size={13} />Reset experiment</button>
            <code>{scenario.snapshot_id}</code>
            <CoverageSourceAttribution
              sources={scenario.attribution_sources}
              fallback={scenario.attribution}
              derivedProcessing={scenario.derived_processing}
            />
          </footer>
        </div>
      </aside>
    </main>
  )
}

function SiteInspector({
  site,
  constraint,
  selected,
  load,
  capacityMultiplier,
  disabled,
  onConstraint,
  onClose,
}: {
  site: ServiceCandidateSite
  constraint: ServiceSiteConstraint
  selected: boolean
  load?: { assigned_population: number; effective_capacity: number; utilisation: number; assigned_cell_count?: number }
  capacityMultiplier: number
  disabled: boolean
  onConstraint: (constraint: ServiceSiteConstraint) => void
  onClose: () => void
}) {
  return (
    <aside className="coverage-site-inspector" aria-label={`Candidate site: ${site.label}`}>
      <header><div><span>Candidate service site</span><h2>{site.label}</h2></div><button type="button" onClick={onClose} aria-label="Close site inspector" autoFocus><X size={16} /></button></header>
      <p>{site.category}</p>
      <dl>
        <div><dt>Solver state</dt><dd>{constraint === 'forced' ? 'Forced selected' : constraint === 'banned' ? 'Excluded' : selected ? 'Selected in current assignment' : 'Available'}</dd></div>
        <div><dt>Analytical capacity</dt><dd>{Math.round(site.capacity_default * capacityMultiplier).toLocaleString('en')} people</dd></div>
        {load && <div><dt>Current load</dt><dd>{Math.round(load.assigned_population).toLocaleString('en')} · {Math.round(load.utilisation * 100)}%</dd></div>}
      </dl>
      <p className="coverage-site-inspector__caution"><TriangleAlert size={12} />{site.capacity_note ?? 'Capacity is a declared scenario assumption and has not been inferred from the building.'}</p>
      <div role="group" aria-label={`Constraint for ${site.label}`}>
        <button type="button" className={constraint === 'forced' ? 'is-active' : ''} aria-pressed={constraint === 'forced'} onClick={() => onConstraint(constraint === 'forced' ? 'free' : 'forced')} disabled={disabled || !site.eligible}><Check size={14} />Force site</button>
        <button type="button" className={constraint === 'banned' ? 'is-active is-ban' : ''} aria-pressed={constraint === 'banned'} onClick={() => onConstraint(constraint === 'banned' ? 'free' : 'banned')} disabled={disabled}><Ban size={14} />Exclude</button>
      </div>
    </aside>
  )
}

function CoverageSourceAttribution({
  sources,
  fallback,
  derivedProcessing,
}: {
  sources: ServiceCoverageAttributionSource[]
  fallback: string
  derivedProcessing: string
}) {
  return (
    <div className="coverage-footer__sources" aria-label="Source attribution and licences">
      <strong>Source evidence · derived / modified</strong>
      <p>{derivedProcessing}</p>
      {sources.length ? (
        <ul>
          {sources.map((source) => (
            <li key={`${source.label}-${source.url}`}>
              <div className="coverage-footer__source-links">
                {source.url ? <a href={source.url} target="_blank" rel="noreferrer" aria-label={`${source.label} source`}>{source.label}</a> : <span>{source.label}</span>}
                {source.licence_url
                  ? <a href={source.licence_url} target="_blank" rel="noreferrer" aria-label={`${source.licence} licence`}>{source.licence}</a>
                  : source.licence}
              </div>
              <p>{source.modifications}</p>
            </li>
          ))}
        </ul>
      ) : <span>{fallback}</span>}
    </div>
  )
}

function CoverageResult({
  status,
  result,
  error,
  scenario,
  budget,
  maxDistance,
  onRaiseBudget,
  onRaiseDistance,
  onRaiseCapacity,
}: {
  status: ExperimentStatus
  result?: ServiceCoverageResult
  error?: string
  scenario: ServiceCoverageScenario
  budget: number
  maxDistance: number
  onRaiseBudget: () => void
  onRaiseDistance: () => void
  onRaiseCapacity: () => void
}) {
  if (status === 'idle' || status === 'solving') return null
  if (status === 'verified_optimal' && result) {
    const worst = result.assignments.reduce((current, assignment) => (
      !current || assignment.distance_m > current.distance_m ? assignment : current
    ), result.assignments[0])
    const worstCell = scenario.population_cells.find((cell) => cell.id === worst?.demand_cell_id)
    const verification = result.verification
    return (
      <section className="coverage-result is-verified" aria-label="Verified service-coverage result">
        <span><ShieldCheck size={18} /></span><div>
          <small>Fresh network verification passed</small>
          <h2>Every included cell is assigned</h2>
          <p>{result.message}</p>
          <dl>
            <div><dt>Sites used</dt><dd>{result.selected_site_ids.length} / {budget}</dd></div>
            <div><dt>Worst distance</dt><dd>{Math.round(result.objective_values?.worst_distance_m ?? worst?.distance_m ?? 0).toLocaleString('en')} m</dd></div>
            <div><dt>Assignments</dt><dd>{result.assignments.length} cells</dd></div>
            <div><dt>Capacity</dt><dd>{verification?.capacities_respected === false ? 'Review' : 'Checked'}</dd></div>
          </dl>
          {worstCell && <p className="coverage-result__witness"><Route size={12} /><span><strong>Worst-served witness</strong>{worstCell.label} · {Math.round(worst?.distance_m ?? 0).toLocaleString('en')} modelled metres, including snap connectors</span></p>}
          <em>This is an optimal assignment under the displayed objectives and assumptions—not evidence of operating capacity, service quality or an implementation recommendation.</em>
        </div>
      </section>
    )
  }
  if (status === 'verified_unsat' && result) {
    const reason = String(result.diagnostics?.finding ?? 'combined_constraints')
    const cellLabel = typeof result.diagnostics?.witness_cell_id === 'string'
      ? scenario.population_cells.find((cell) => cell.id === result.diagnostics?.witness_cell_id)?.label
      : undefined
    return (
      <section className="coverage-result is-unsat" aria-label="Verified infeasible service-coverage request">
        <span><TriangleAlert size={18} /></span><div>
          <small>Verified infeasible under encoded assumptions</small>
          <h2>{reason === 'distance_coverage_gap' ? 'A cell has no eligible site within range' : reason === 'insufficient_capacity_under_budget' ? 'Available analytical capacity is insufficient' : 'The current limits cannot cover every cell'}</h2>
          <p>{result.message}{cellLabel ? ` The mapped witness is ${cellLabel}.` : ''} This does not prove that no real service arrangement exists.</p>
          <div className="coverage-result__relaxations" aria-label="Suggested relaxations">
            {(reason === 'distance_coverage_gap' || reason === 'incompatible_service_assumptions' || reason === 'combined_constraints') && <button type="button" onClick={onRaiseDistance}>Try {Math.min(2400, maxDistance + 200).toLocaleString('en')} m</button>}
            {reason !== 'distance_coverage_gap' && <button type="button" onClick={onRaiseBudget}>Try budget {budget + 1}</button>}
            {(reason === 'insufficient_capacity_under_budget' || reason === 'incompatible_service_assumptions' || reason === 'combined_constraints') && <button type="button" onClick={onRaiseCapacity}>Test 125% capacity</button>}
          </div>
        </div>
      </section>
    )
  }
  return (
    <section className="coverage-result is-indeterminate" aria-label="Indeterminate service-coverage result">
      <span><TriangleAlert size={18} /></span><div><small>Indeterminate — not UNSAT</small><h2>{status === 'timeout' ? 'Solver timed out' : status === 'cancelled' ? 'Solve cancelled' : 'Data or verification error'}</h2><p>{error ?? result?.message ?? 'No verified conclusion was produced.'}</p></div>
    </section>
  )
}

function CoverageSolveTrace({ events }: { events: ServiceCoverageSolveEvent[] }) {
  if (!events.length) return null
  const stages = [
    { type: 'matrix_compiled', label: 'Frozen walking matrix', detail: 'GIS supplied the complete frozen cell–site matrix; unavailable pairs are false.' },
    { type: 'feasible_assignment', label: 'Feasible assignment', detail: 'Z3 found a first assignment satisfying every hard rule.' },
    { type: 'objective_improved', label: 'Lexicographic search', detail: 'Z3 proved each objective minimum in priority order.' },
    { type: 'fresh_verification', label: 'Evidence checked afresh', detail: 'NetworkX rebuilt routes and all hard rules were recomputed.' },
  ] as const
  const eventTypes = new Set(events.map((event) => event.type))
  const latest = events.at(-1)
  return (
    <section className="coverage-trace" aria-label="Solver stage trace">
      <header><span>Actual solve stages</span><strong>{events.length} events</strong></header>
      <ol>
        {stages.map((stage, index) => {
          const complete = eventTypes.has(stage.type)
          const active = latest?.type === stage.type
          const stageEvent = [...events].reverse().find((event) => event.type === stage.type)
          return <li key={stage.type} className={`${complete ? 'is-complete' : ''} ${active ? 'is-active' : ''}`}><i>{complete ? <Check size={11} /> : index + 1}</i><span><strong>{stage.label}</strong><small>{stageEvent?.message ?? stage.detail}</small></span></li>
        })}
      </ol>
    </section>
  )
}

function constraintFor(siteId: string, forced: string[], banned: string[]): ServiceSiteConstraint {
  if (forced.includes(siteId)) return 'forced'
  if (banned.includes(siteId)) return 'banned'
  return 'free'
}

function terminalStatus(type: ServiceCoverageSolveEvent['type']): ServiceCoverageStatus | undefined {
  return type === 'verified_optimal' || type === 'verified_unsat' || type === 'timeout' || type === 'cancelled' || type === 'data_error'
    ? type
    : undefined
}
