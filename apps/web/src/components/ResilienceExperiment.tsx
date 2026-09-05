import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { RefObject } from 'react'
import type { Feature, FeatureCollection, Geometry, LineString, MultiLineString } from 'geojson'
import {
  BookOpenText,
  Braces,
  Check,
  ChevronDown,
  CircleStop,
  Construction,
  Database,
  LoaderCircle,
  Minus,
  Plus,
  RotateCcw,
  Route,
  ShieldCheck,
  TriangleAlert,
  Waves,
  X,
} from 'lucide-react'
import {
  ApiError,
  cancelResilienceSolve,
  getResilienceScenario,
  streamResilienceSolve,
} from '../api'
import type {
  ResilienceAccessRecord,
  ResilienceAnalysis,
  ResilienceDecisionGroup,
  ResilienceResultStatus,
  ResilienceScenario,
  ResilienceSolveEvent,
  ResilienceSolveRequest,
  ResilienceSolveResult,
} from '../types'
import {
  ConstraintWorkbench,
  type ConstraintTraceEvent,
} from './ConstraintWorkbench'
import {
  ResilienceAnalysisMap,
  type ResilienceMapLocation,
  type ResilienceMapSegmentPick,
  type ResilienceMapView,
} from './ResilienceAnalysisMap'
import { ScenarioBuilderDrawer } from './ScenarioBuilderDrawer'
import './ResilienceExperiment.css'

type ExperimentStatus = 'idle' | 'solving' | ResilienceResultStatus

const EMPTY_LINES: FeatureCollection<LineString | MultiLineString> = {
  type: 'FeatureCollection',
  features: [],
}

export function ResilienceExperiment({ active = true }: { active?: boolean }) {
  const [scenario, setScenario] = useState<ResilienceScenario>()
  const [loadError, setLoadError] = useState<string>()
  const [reloadKey, setReloadKey] = useState(0)
  const [returnPeriod, setReturnPeriod] = useState<100 | 1000>(1000)
  const [treatExposureUnavailable, setTreatExposureUnavailable] = useState(true)
  const [originIds, setOriginIds] = useState<string[]>([])
  const [gatewayIds, setGatewayIds] = useState<string[]>([])
  const [repairBudget, setRepairBudget] = useState(4)
  const [timeoutSeconds, setTimeoutSeconds] = useState(30)
  const [roadworksIds, setRoadworksIds] = useState<string[]>([])
  const [editingRoadworks, setEditingRoadworks] = useState(false)
  const [events, setEvents] = useState<ResilienceSolveEvent[]>([])
  const [result, setResult] = useState<ResilienceSolveResult>()
  const [status, setStatus] = useState<ExperimentStatus>('idle')
  const [mapView, setMapView] = useState<ResilienceMapView>('disrupted')
  const [eventCursor, setEventCursor] = useState<number | 'live'>('live')
  const [showWorkbench, setShowWorkbench] = useState(false)
  const [showEvidence, setShowEvidence] = useState(false)
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [runError, setRunError] = useState<string>()
  const abortRef = useRef<AbortController | undefined>(undefined)
  const solveIdRef = useRef<string | undefined>(undefined)
  const terminalStatusRef = useRef<ExperimentStatus>('idle')
  const workbenchDialogRef = useRef<HTMLDivElement>(null)
  const closeWorkbench = useCallback(() => setShowWorkbench(false), [])

  useModalDialog(showWorkbench, workbenchDialogRef, closeWorkbench)

  useEffect(() => {
    const controller = new AbortController()
    setLoadError(undefined)
    getResilienceScenario(controller.signal)
      .then((loaded) => {
        setScenario(loaded)
        setReturnPeriod(loaded.defaults.flood_return_period_years)
        setTreatExposureUnavailable(loaded.defaults.treat_flood_exposure_as_unavailable)
        setOriginIds(loaded.defaults.origin_ids)
        setGatewayIds(loaded.defaults.gateway_group_ids)
        setRepairBudget(loaded.defaults.analytical_repair_budget)
        setTimeoutSeconds(loaded.defaults.timeout_seconds)
      })
      .catch((caught: unknown) => {
        if ((caught as Error).name !== 'AbortError') {
          setLoadError(caught instanceof ApiError ? caught.message : 'The frozen Otaniemi analysis could not be loaded.')
        }
      })
    return () => controller.abort()
  }, [reloadKey])

  useEffect(() => () => {
    const solveId = solveIdRef.current
    const solveWasActive = Boolean(abortRef.current)
    abortRef.current?.abort()
    abortRef.current = undefined
    if (solveWasActive && solveId) void cancelResilienceSolve(solveId).catch(() => undefined)
  }, [])

  useEffect(() => {
    if (active || !abortRef.current) return
    const solveId = solveIdRef.current
    abortRef.current.abort()
    abortRef.current = undefined
    setStatus('cancelled')
    terminalStatusRef.current = 'cancelled'
    setRunError('The analysis was cancelled when you left the experiment. No feasibility conclusion was reached.')
    if (solveId) void cancelResilienceSolve(solveId).catch(() => undefined)
  }, [active])

  const resetOutcome = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = undefined
    solveIdRef.current = undefined
    setEvents([])
    setResult(undefined)
    setRunError(undefined)
    setStatus('idle')
    terminalStatusRef.current = 'idle'
    setMapView('disrupted')
    setEventCursor('live')
  }, [])

  const updateScenario = useCallback((change: () => void) => {
    change()
    resetOutcome()
  }, [resetOutcome])

  const decisionGroups = useMemo(
    () => treatExposureUnavailable
      ? scenario?.decision_groups_by_return_period[String(returnPeriod) as '100' | '1000'] ?? []
      : [],
    [returnPeriod, scenario, treatExposureUnavailable],
  )
  const effectiveExposedIds = useMemo(
    () => exposureSegmentIds(scenario, returnPeriod),
    [returnPeriod, scenario],
  )
  const effectiveUnavailableIds = useMemo(
    () => Array.from(new Set([
      ...(treatExposureUnavailable ? effectiveExposedIds : []),
      ...roadworksIds,
    ])).sort(),
    [effectiveExposedIds, roadworksIds, treatExposureUnavailable],
  )
  const activeEvent = eventCursor === 'live' ? events.at(-1) : events[eventCursor]
  const activeEventIndex = eventCursor === 'live' ? events.length - 1 : eventCursor
  const activeCandidate = activeEvent?.selected_decision_ids
    ? activeEvent
    : events.slice(0, activeEventIndex + 1).reverse().find((event) => (
      event.type === 'candidate_found'
      && (activeEvent?.iteration == null || event.iteration === activeEvent.iteration)
    ))
  const isSolving = status === 'solving'
  const isDefaultScenario = Boolean(scenario
    && returnPeriod === scenario.defaults.flood_return_period_years
    && treatExposureUnavailable === scenario.defaults.treat_flood_exposure_as_unavailable
    && roadworksIds.length === 0
    && sameIds(originIds, scenario.defaults.origin_ids)
    && sameIds(gatewayIds, scenario.defaults.gateway_group_ids))
  const visibleResult = activeEvent?.result ?? (eventCursor === 'live' ? result : undefined)

  const accessRecords = useMemo(() => {
    if (Array.isArray(activeEvent?.access)) return activeEvent.access
    if (Array.isArray(activeCandidate?.access)) return activeCandidate.access
    if (visibleResult?.analysis?.access) return visibleResult.analysis.access
    if (visibleResult?.baseline_disruption_analysis?.access) return visibleResult.baseline_disruption_analysis.access
    return isDefaultScenario ? scenario?.default_disruption_analysis.access : undefined
  }, [activeCandidate?.access, activeEvent?.access, isDefaultScenario, scenario?.default_disruption_analysis.access, visibleResult])
  const activeAnalysis = visibleResult?.analysis
    ?? visibleResult?.baseline_disruption_analysis
    ?? (isDefaultScenario ? scenario?.default_disruption_analysis : undefined)
  const selectedDecisionIds = activeEvent?.selected_decision_ids
    ?? activeCandidate?.selected_decision_ids
    ?? visibleResult?.selected_decision_ids
    ?? []
  const selectedSegmentIds = activeEvent?.selected_segment_ids
    ?? activeCandidate?.selected_segment_ids
    ?? visibleResult?.selected_segment_ids
    ?? []
  const counterexampleRoute = featureCollection(activeEvent?.route)
  const reachableRoutes = routesFor(accessRecords, 'disrupted_route', 'retained')
  const affectedRoutes = routesFor(accessRecords, 'baseline_route', 'stranded')
  const reachableSegmentIds = useMemo(
    () => activeEvent?.reachable_segment_ids ?? Array.from(new Set(
      (accessRecords ?? []).flatMap((record) => record.disrupted_route?.physical_segment_ids ?? []),
    )),
    [accessRecords, activeEvent?.reachable_segment_ids],
  )
  const locations = useMemo(
    () => scenario ? mapLocations(scenario, originIds, gatewayIds, accessRecords) : [],
    [accessRecords, gatewayIds, originIds, scenario],
  )

  const solve = useCallback(async () => {
    if (!scenario || !originIds.length || !gatewayIds.length) return
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    setEvents([])
    setResult(undefined)
    setRunError(undefined)
    setStatus('solving')
    terminalStatusRef.current = 'solving'
    setMapView('disrupted')
    setEventCursor('live')
    const request: ResilienceSolveRequest = {
      scenario_id: scenario.id,
      flood_return_period_years: returnPeriod,
      treat_flood_exposure_as_unavailable: treatExposureUnavailable,
      roadworks_segment_ids: roadworksIds,
      origin_ids: originIds,
      gateway_group_ids: gatewayIds,
      analytical_repair_budget: repairBudget,
      timeout_seconds: timeoutSeconds,
    }
    try {
      const final = await streamResilienceSolve(request, (event) => {
        if (event.solve_id) solveIdRef.current = event.solve_id
        setEvents((current) => [...current, event])
        setEventCursor('live')
        if (event.type === 'candidate_found' || event.type === 'counterexample_found') setMapView('disrupted')
        const terminalStatus = resilienceTerminalStatus(event.type)
        if (terminalStatus) {
          terminalStatusRef.current = terminalStatus
          setStatus(terminalStatus)
          if (terminalStatus === 'data_error') {
            setRunError(event.message ?? 'The resilience stream reported a data or verification error.')
          }
        }
        if (event.result) {
          setResult(event.result)
          setStatus(event.result.status)
          terminalStatusRef.current = event.result.status
          setMapView(event.result.status === 'verified_optimal' ? 'verified' : 'disrupted')
        }
      }, controller.signal)
      if (final) {
        setResult(final)
        setStatus(final.status)
        terminalStatusRef.current = final.status
        setMapView(final.status === 'verified_optimal' ? 'verified' : 'disrupted')
      } else if (terminalStatusRef.current === 'solving') {
        terminalStatusRef.current = 'data_error'
        setStatus('data_error')
        setRunError('The resilience progress stream ended without a verified terminal result.')
      }
    } catch (caught: unknown) {
      if ((caught as Error).name !== 'AbortError') {
        setRunError(caught instanceof ApiError ? caught.message : 'The access analysis stream was interrupted.')
        setStatus('data_error')
        terminalStatusRef.current = 'data_error'
      }
    } finally {
      if (abortRef.current === controller) abortRef.current = undefined
    }
  }, [
    gatewayIds,
    originIds,
    repairBudget,
    returnPeriod,
    roadworksIds,
    scenario,
    timeoutSeconds,
    treatExposureUnavailable,
  ])

  const cancel = useCallback(() => {
    const solveId = solveIdRef.current
    abortRef.current?.abort()
    abortRef.current = undefined
    setStatus('cancelled')
    terminalStatusRef.current = 'cancelled'
    setRunError('The run was cancelled. No feasibility conclusion was reached.')
    if (solveId) void cancelResilienceSolve(solveId).catch(() => undefined)
  }, [])

  const reset = useCallback(() => {
    resetOutcome()
    if (!scenario) return
    setReturnPeriod(scenario.defaults.flood_return_period_years)
    setTreatExposureUnavailable(scenario.defaults.treat_flood_exposure_as_unavailable)
    setOriginIds(scenario.defaults.origin_ids)
    setGatewayIds(scenario.defaults.gateway_group_ids)
    setRepairBudget(scenario.defaults.analytical_repair_budget)
    setTimeoutSeconds(scenario.defaults.timeout_seconds)
    setRoadworksIds([])
    setEditingRoadworks(false)
  }, [resetOutcome, scenario])

  const toggleRoadwork = useCallback((segment: ResilienceMapSegmentPick) => {
    if (!editingRoadworks) return
    updateScenario(() => setRoadworksIds((current) => (
      current.includes(segment.id)
        ? current.filter((id) => id !== segment.id)
        : [...current, segment.id].sort()
    )))
  }, [editingRoadworks, updateScenario])

  const selectLocation = useCallback((location: ResilienceMapLocation) => {
    if (!scenario) return
    if (location.kind === 'origin') {
      updateScenario(() => setOriginIds((current) => toggleId(current, location.id)))
    } else {
      updateScenario(() => setGatewayIds((current) => toggleId(current, location.id)))
    }
  }, [scenario, updateScenario])

  if (!scenario) {
    return (
      <main className="resilience-loading">
        {loadError ? <TriangleAlert size={26} /> : <LoaderCircle className="spin" size={24} />}
        <h1 data-page-heading tabIndex={-1}>{loadError ? 'Otaniemi analysis unavailable' : 'Loading the frozen Otaniemi graph'}</h1>
        <p>{loadError ?? 'Preparing 8,048 private-car street segments, municipal context, and flood-overlap evidence…'}</p>
        {loadError && <button type="button" onClick={() => setReloadKey((value) => value + 1)}>Retry</button>}
      </main>
    )
  }

  const summary = activeEvent?.access_summary ?? activeCandidate?.access_summary ?? activeAnalysis?.summary
  const runDecisionGroups = result?.decision_groups ?? decisionGroups
  const selectedGroups = (result?.selected_decisions ?? selectedDecisionIds
    .map((id) => runDecisionGroups.find((group) => group.id === id)))
    .filter((group): group is ResilienceDecisionGroup => Boolean(group))

  return (
    <main className="resilience-experiment">
      <aside className="resilience-instrument" aria-label="Otaniemi access scenario controls" inert={showWorkbench || showEvidence ? true : undefined} aria-hidden={showWorkbench || showEvidence ? true : undefined}>
        <div className="resilience-instrument__scroll">
          <section className="resilience-intro">
            <div className="resilience-intro__kicker"><Waves size={14} />Experiment 02 · frozen Otaniemi</div>
            <h1 data-page-heading tabIndex={-1}>See what stays reachable when road links are unavailable.</h1>
            <p>Turn published exposure into an explicit stress-test assumption, then watch a constraint solver search for the smallest set of continuity commitments.</p>
            <div className="resilience-scope-chip"><span>Private-car graph</span><span>15 representative 500 m cells</span><span>4 reviewed network exits</span></div>
          </section>

          <section className="resilience-control" aria-labelledby="hazard-control-title">
            <header><span>01</span><div><h2 id="hazard-control-title">Declare the disruption</h2><p>Published overlap is evidence. This switch is the closure assumption.</p></div></header>
            <div className="return-period" role="group" aria-label="Flood stress-test return period">
              {([100, 1000] as const).map((period) => (
                <button
                  type="button"
                  key={period}
                  className={returnPeriod === period ? 'is-active' : ''}
                  aria-pressed={returnPeriod === period}
                  onClick={() => updateScenario(() => setReturnPeriod(period))}
                  disabled={isSolving}
                >
                  <strong>1/{period.toLocaleString('en-US')}</strong>
                  <small>{scenario.counts.private_car_exposed_segments[String(period) as '100' | '1000']} car links</small>
                </button>
              ))}
            </div>
            <p className="return-period__meaning">1/{returnPeriod.toLocaleString('en-US')} contains {scenario.counts.source_exposed_segments[String(returnPeriod) as '100' | '1000'].toLocaleString('en')} source-exposed network segments; {scenario.counts.private_car_exposed_segments[String(returnPeriod) as '100' | '1000'].toLocaleString('en')} affect this private-car graph. 1/100 ≈ 1% annual exceedance probability; 1/1,000 ≈ 0.1%. Neither is a forecast or periodic schedule.</p>
            <label className="resilience-assumption">
              <input
                type="checkbox"
                checked={treatExposureUnavailable}
                onChange={(event) => updateScenario(() => setTreatExposureUnavailable(event.target.checked))}
                disabled={isSolving}
              />
              <span><strong>Treat exposed links as unavailable</strong><small>Conservative analytical stress test—not an observed closure or safety finding</small></span>
              <i aria-hidden="true" />
            </label>
            <button
              type="button"
              className={`roadworks-tool ${editingRoadworks ? 'is-active' : ''}`}
              onClick={() => setEditingRoadworks((value) => !value)}
              aria-pressed={editingRoadworks}
              disabled={isSolving}
            >
              <Construction size={15} />
              <span><strong>{editingRoadworks ? 'Click streets to declare works' : 'Add a roadworks closure on map'}</strong><small>{roadworksIds.length ? `${roadworksIds.length} fixed unavailable link${roadworksIds.length === 1 ? '' : 's'}` : 'Optional user-declared scenario'}</small></span>
              {editingRoadworks && <Check size={14} />}
            </button>
          </section>

          <section className="resilience-control" aria-labelledby="access-control-title">
            <header><span>02</span><div><h2 id="access-control-title">Require access</h2><p>{originIds.length} of {scenario.origins.length} representative address cells must reach at least one selected network exit.</p></div></header>
            <div className="analysis-presets" role="group" aria-label="Origin sensitivity preset">
              <button
                type="button"
                className={sameIds(originIds, scenario.analysis_presets.teaching_focus.origin_ids) ? 'is-active' : ''}
                onClick={() => updateScenario(() => {
                  setOriginIds(scenario.analysis_presets.teaching_focus.origin_ids)
                  setGatewayIds(scenario.analysis_presets.teaching_focus.gateway_group_ids)
                })}
                disabled={isSolving}
              ><strong>Teaching focus</strong><small>1 representative cell · fast trace</small></button>
              <button
                type="button"
                className={sameIds(originIds, scenario.analysis_presets.all_origins_sensitivity.origin_ids) ? 'is-active' : ''}
                onClick={() => updateScenario(() => {
                  setOriginIds(scenario.analysis_presets.all_origins_sensitivity.origin_ids)
                  setGatewayIds(scenario.analysis_presets.all_origins_sensitivity.gateway_group_ids)
                })}
                disabled={isSolving}
              ><strong>All-cell sensitivity</strong><small>15 representatives · slower</small></button>
            </div>
            <div className="gateway-grid">
              {scenario.gateway_groups.map((gateway) => (
                <button
                  key={gateway.id}
                  type="button"
                  className={gatewayIds.includes(gateway.id) ? 'is-active' : ''}
                  aria-pressed={gatewayIds.includes(gateway.id)}
                  onClick={() => updateScenario(() => setGatewayIds((current) => toggleId(current, gateway.id)))}
                  disabled={isSolving}
                ><span>{gateway.direction.slice(0, 1).toUpperCase()}</span><strong>{gateway.direction}</strong><small>{gateway.label.split('·')[1]?.trim()}</small></button>
              ))}
            </div>
            <p className="resilience-fineprint">Each origin may reach <strong>any one</strong> selected exit (OR semantics). Exits are reviewed graph endpoints, not certified shelters or safe destinations. Click map symbols to include or exclude them.</p>
          </section>

          <section className="resilience-control resilience-budget" aria-labelledby="repair-budget-title">
            <header><span>03</span><div><h2 id="repair-budget-title">Limit continuity commitments</h2><p>One Boolean groups connected flood-exposed links. It cannot reopen declared roadworks; verification still checks every OSM edge.</p></div></header>
            <div className="resilience-budget__value">
              <button type="button" aria-label="Decrease continuity budget" onClick={() => updateScenario(() => setRepairBudget((value) => Math.max(0, value - 1)))} disabled={isSolving || repairBudget === 0}><Minus size={16} /></button>
              <output aria-label={`${repairBudget} continuity commitments`}><strong>{repairBudget}</strong><span>zones<br />maximum</span></output>
              <button type="button" aria-label="Increase continuity budget" onClick={() => updateScenario(() => setRepairBudget((value) => Math.min(16, value + 1)))} disabled={isSolving || repairBudget === 16}><Plus size={16} /></button>
            </div>
            <input
              type="range"
              min="0"
              max="16"
              value={repairBudget}
              onChange={(event) => updateScenario(() => setRepairBudget(Number(event.target.value)))}
              aria-label="Continuity commitment budget"
              disabled={isSolving}
            />
          </section>

          <button
            type="button"
            className={`resilience-solve ${isSolving ? 'is-solving' : ''}`}
            onClick={isSolving ? cancel : solve}
            disabled={!isSolving && (!originIds.length || !gatewayIds.length)}
          >
            <span>{isSolving ? <CircleStop size={18} /> : <Route size={18} />}</span>
            <span><strong>{isSolving ? 'Cancel analysis' : `Solve access with ${repairBudget}`}</strong><small>{isSolving ? 'Keep timeout distinct from infeasible' : 'Z3 proposal · NetworkX check · fresh verification'}</small></span>
            {isSolving ? <LoaderCircle className="spin" size={17} /> : <span aria-hidden="true">→</span>}
          </button>

          <ResultSummary
            status={status}
            result={result}
            summary={summary}
            error={runError}
            budget={repairBudget}
            selectedGroups={selectedGroups}
            selectedSegmentCount={result?.selected_segment_ids?.length ?? selectedSegmentIds.length}
            onRaiseBudget={() => updateScenario(() => setRepairBudget((value) => Math.min(16, value + 2)))}
          />

          <SolverTrace events={events} cursor={eventCursor} onSelect={(next) => {
            setEventCursor(next)
            if (next === 'live' && result?.status === 'verified_optimal') setMapView('verified')
            else setMapView('disrupted')
          }} />

          <button type="button" className="constraint-preview" onClick={() => setShowWorkbench(true)}>
            <Braces size={19} />
            <span><small>How the map enters Z3</small><code>Σ continuity[zone] ≤ {repairBudget}</code><strong>Open constraint workbench</strong></span>
            <span aria-hidden="true">→</span>
          </button>

          <details className="resilience-details" open={advancedOpen} onToggle={(event) => setAdvancedOpen(event.currentTarget.open)}>
            <summary><BookOpenText size={15} /><span><strong>Scope, data & runtime</strong><small>{timeoutSeconds}s limit · frozen replay</small></span><ChevronDown size={15} /></summary>
            <div>
              <label>Solver timeout
                <select value={timeoutSeconds} onChange={(event) => updateScenario(() => setTimeoutSeconds(Number(event.target.value)))} disabled={isSolving}>
                  {[10, 30, 60, 120].map((seconds) => <option value={seconds} key={seconds}>{seconds} seconds</option>)}
                </select>
              </label>
              <p><strong>What “verified” means:</strong> all selected origin-to-context reachability checks pass in a freshly rebuilt directed graph under the stated assumptions. It does not establish flood depth, velocity, road operability, legal access, or emergency-service approval.</p>
              <button type="button" onClick={() => setShowEvidence(true)}><Database size={14} />Study area, sources & location builder</button>
            </div>
          </details>

          <footer className="resilience-footer">
            <button type="button" onClick={reset} disabled={isSolving}><RotateCcw size={13} />Reset experiment</button>
            <code>{scenario.snapshot_id}</code>
            <span>OSM · ODbL / Syke & Espoo · CC BY 4.0</span>
          </footer>
        </div>
      </aside>

      <section className={`resilience-map-region ${editingRoadworks ? 'is-editing-roadworks' : ''}`} aria-label="Otaniemi disruption analysis map" inert={showWorkbench || showEvidence ? true : undefined} aria-hidden={showWorkbench || showEvidence ? true : undefined}>
        {editingRoadworks && <div className="roadworks-banner"><Construction size={14} /><strong>Roadworks input</strong><span>Click a private-car street to toggle an explicit closure.</span><button type="button" onClick={() => setEditingRoadworks(false)}>Done</button></div>}
        <ResilienceAnalysisMap
          baseNetwork={scenario.base_network}
          buildings={scenario.buildings}
          floodExposure={scenario.flood_exposure}
          unavailableSegmentIds={effectiveUnavailableIds}
          selectedRoadworkSegmentIds={roadworksIds}
          reachableSegmentIds={reachableSegmentIds}
          reachableRoutes={reachableRoutes}
          affectedRoutes={affectedRoutes}
          counterexampleRoute={counterexampleRoute}
          frontierSegmentIds={activeEvent?.frontier_segment_ids}
          repairSegmentIds={selectedSegmentIds}
          commitmentCount={selectedDecisionIds.length}
          locations={locations}
          selectedReturnPeriod={returnPeriod}
          view={mapView}
          onViewChange={(nextView) => {
            setMapView(nextView)
            if (nextView !== 'disrupted') setEventCursor('live')
          }}
          center={scenario.center}
          bbox={scenario.bbox}
          title="Otaniemi coastal access"
          snapshotId={scenario.snapshot_id}
          solving={isSolving}
          iteration={activeEvent?.iteration}
          statusMessage={activeEvent?.message ?? result?.message}
          verifiedAvailable={result?.status === 'verified_optimal'}
          onNetworkSegmentToggle={isSolving ? undefined : toggleRoadwork}
          onLocationSelect={isSolving ? undefined : selectLocation}
          dataAttribution="Syke flood overlap · City of Espoo addresses/buildings"
        />
      </section>

      {showWorkbench && (
        <div className="resilience-sheet-layer" role="dialog" aria-modal="true" aria-labelledby="constraint-workbench-dialog-title">
          <button type="button" className="resilience-sheet-layer__backdrop" onClick={closeWorkbench} aria-label="Close constraint workbench" />
          <div className="resilience-workbench-sheet" ref={workbenchDialogRef} tabIndex={-1}>
            <header><div><span>Method you can inspect</span><strong id="constraint-workbench-dialog-title">Constraint solver workbench</strong></div><button type="button" onClick={closeWorkbench} aria-label="Close constraint workbench" data-dialog-close><X size={18} /></button></header>
            <ConstraintWorkbench
              scenarioLabel={`Otaniemi · 1/${returnPeriod.toLocaleString('en-US')} stress test · private-car mode`}
              budget={repairBudget}
              hazardClosureCount={treatExposureUnavailable ? effectiveExposedIds.length : 0}
              roadworksClosureCount={roadworksIds.length}
              origins={scenario.origins.filter((origin) => originIds.includes(origin.id)).map((origin) => ({ id: origin.id, name: origin.label }))}
              destinations={scenario.gateway_groups.filter((gateway) => gatewayIds.includes(gateway.id)).map((gateway) => ({ id: gateway.id, name: gateway.label }))}
              decisionLinks={runDecisionGroups.map((group) => ({ id: group.id, name: `${group.label} · ${group.length_m.toLocaleString('en')} m` }))}
              events={events.map(workbenchEvent)}
              result={result ? {
                status: humanStatus(result.status),
                selectedDecisionIds: result.selected_decision_ids,
                verifiedOriginIds: Object.entries(result.verification?.origin_access ?? {}).filter(([, served]) => served).map(([id]) => id),
                unservedOriginIds: (result.analysis ?? result.baseline_disruption_analysis)?.access.filter((record) => record.status !== 'retained').map((record) => record.origin.id) ?? [],
                explanation: result.message,
              } : null}
              hazardLayerLabel={`Syke 1/${returnPeriod.toLocaleString('en-US')} horizontal overlap`}
            />
          </div>
        </div>
      )}

      {showEvidence && (
        <div className="resilience-sheet-layer">
          <div className="resilience-sheet-layer__backdrop" aria-hidden="true" />
          <ScenarioBuilderDrawer onClose={() => setShowEvidence(false)} />
        </div>
      )}
    </main>
  )
}

function ResultSummary({
  status,
  result,
  summary,
  error,
  budget,
  selectedGroups,
  selectedSegmentCount,
  onRaiseBudget,
}: {
  status: ExperimentStatus
  result?: ResilienceSolveResult
  summary?: ResilienceAnalysis['summary']
  error?: string
  budget: number
  selectedGroups: ResilienceDecisionGroup[]
  selectedSegmentCount: number
  onRaiseBudget: () => void
}) {
  if (status === 'idle' && !summary) return null
  if (status === 'idle' && summary) {
    return (
      <section className="resilience-result is-preview" aria-label="Default disruption preview">
        <span><Waves size={16} /></span><div><small>Precomputed vulnerability</small><h2>{summary.stranded ? `${summary.stranded} representative origin cells lose access` : 'All selected representatives retain access'}</h2><p>Run the solver to test whether a limited set of corridor-scale continuity commitments restores the graph.</p></div>
      </section>
    )
  }
  if (status === 'solving') return null
  if (status === 'verified_optimal' && result) {
    const verifiedSummary = result.analysis?.summary
    const retained = result.analysis?.access.filter((record) => record.status === 'retained') ?? []
    const maximumDetour = Math.max(0, ...retained.map((record) => record.detour_m ?? 0))
    const usesServiceLinks = selectedGroups.some((group) => group.highway === 'service')
    const aggregationCost = result.objective_values?.decision_group_cost
    return (
      <section className="resilience-result is-verified" aria-label="Verified resilient-access result">
        <span><ShieldCheck size={18} /></span><div>
          <small>Fresh directed-graph check passed</small>
          <h2>Access verified under this model</h2>
          <p>{verifiedSummary?.retained ?? result.origin_ids.length} of {result.origin_ids.length} representative origin cells reach at least one selected network exit.</p>
          <dl className="resilience-result__metrics">
            <div><dt>Commitments</dt><dd>{selectedGroups.length} zones</dd></div>
            <div><dt>Expansion</dt><dd>{selectedSegmentCount} links</dd></div>
            <div><dt>Mapped detour</dt><dd>+{Math.round(maximumDetour).toLocaleString('en')} m</dd></div>
            {aggregationCost != null && <div><dt>Length cost</dt><dd>{aggregationCost.toLocaleString('en')} m</dd></div>}
          </dl>
          {usesServiceLinks && <p className="resilience-result__warning"><TriangleAlert size={12} />The minimum dependency uses mapped service or driveway links. Missing OSM restrictions do not establish public or legal access; field review is essential.</p>}
          <em>A selected zone belongs to this returned optimum; an equally good alternative may differ. It is not a finding that its roads are open, safe, legal, or physically passable.</em>
        </div>
      </section>
    )
  }
  if (status === 'verified_unsat' && result) {
    const unrepairableCut = result.diagnostics?.finding === 'unrepairable_access_cut'
    return (
      <section className="resilience-result is-unsat" aria-label={unrepairableCut ? 'Verified unrepairable graph cut' : 'Verified insufficient continuity budget'}>
        <span><TriangleAlert size={18} /></span><div>
          <small>Verified infeasible under encoded choices</small>
          <h2>{unrepairableCut ? 'No eligible continuity choice crosses this cut' : `${budget} commitments are insufficient`}</h2>
          <p>{result.message} {unrepairableCut ? 'Increasing the budget alone cannot change this finding; review fixed closures, decision eligibility, required origins, or permitted exits.' : 'This does not mean that no physical or operational solution exists.'}</p>
          {!unrepairableCut && <button type="button" onClick={onRaiseBudget}>Try budget {Math.min(16, budget + 2)}</button>}
        </div>
      </section>
    )
  }
  return (
    <section className="resilience-result is-indeterminate" aria-label="Indeterminate resilience result">
      <span><TriangleAlert size={18} /></span><div><small>Indeterminate — not UNSAT</small><h2>{status === 'timeout' ? 'Solver timed out' : status === 'cancelled' ? 'Analysis cancelled' : 'Analysis error'}</h2><p>{error ?? result?.message ?? 'No verified conclusion was produced.'}</p></div>
    </section>
  )
}

function SolverTrace({
  events,
  cursor,
  onSelect,
}: {
  events: ResilienceSolveEvent[]
  cursor: number | 'live'
  onSelect: (value: number | 'live') => void
}) {
  if (!events.length) return null
  return (
    <section className="resilience-trace" aria-label="Solver iteration timeline">
      <header><span>Live solve trace</span><strong>{events.length} events</strong>{cursor !== 'live' && <button type="button" onClick={() => onSelect('live')}>Follow latest</button>}</header>
      <ol>
        {events.slice(-8).map((event, visibleIndex) => {
          const index = Math.max(0, events.length - 8) + visibleIndex
          const active = cursor === index || (cursor === 'live' && index === events.length - 1)
          return <li key={`${event.type}-${event.iteration ?? index}-${index}`}><button type="button" className={active ? 'is-active' : ''} onClick={() => onSelect(index)}><i className={`is-${event.type}`} /><span><small>{event.iteration ? `Iteration ${event.iteration}` : event.type.replaceAll('_', ' ')}</small><strong>{event.message ?? traceLabel(event)}</strong></span></button></li>
        })}
      </ol>
    </section>
  )
}

function traceLabel(event: ResilienceSolveEvent): string {
  if (event.type === 'started') return 'Compiled map facts into an explicit availability scenario.'
  if (event.type === 'candidate_found') return 'Z3 proposed a continuity-zone assignment.'
  if (event.type === 'counterexample_found') return 'NetworkX found a stranded origin and returned a graph frontier.'
  if (event.type === 'unrepairable_cut') return 'The directed cut contains no eligible continuity-zone decision.'
  if (event.type === 'verified_optimal') return 'A fresh graph recomputed every required access relation.'
  if (event.type === 'verified_unsat') return event.result?.diagnostics?.finding === 'unrepairable_access_cut'
    ? 'No eligible decision crosses the verified directed cut.'
    : 'The learned necessary cuts exceed the current budget.'
  return 'Analysis state changed.'
}

function workbenchEvent(event: ResilienceSolveEvent, index: number): ConstraintTraceEvent {
  return {
    id: `${event.type}-${event.iteration ?? index}-${index}`,
    type: event.type,
    iteration: event.iteration,
    message: event.message,
    selectedDecisionIds: event.selected_decision_ids,
    witnessEdgeIds: event.witness_segment_ids,
    learnedClauseIds: event.learned_clause_ids ?? event.frontier_decision_ids,
    constraint: event.constraint_expression,
    originId: event.origin_id,
  }
}

function exposureSegmentIds(scenario: ResilienceScenario | undefined, period: 100 | 1000): string[] {
  if (!scenario) return []
  return Array.from(new Set(scenario.flood_exposure.features
    .filter((feature) => Number(feature.properties?.return_period_years) === period)
    .map((feature) => String(feature.properties?.physical_segment_id ?? ''))
    .filter(Boolean))).sort()
}

function routesFor(
  records: ResilienceAccessRecord[] | undefined,
  key: 'baseline_route' | 'disrupted_route',
  status: ResilienceAccessRecord['status'],
): FeatureCollection<LineString | MultiLineString> {
  const features = (records ?? []).flatMap((record) => {
    const feature = record.status === status ? record[key]?.feature : undefined
    if (!feature || (feature.geometry.type !== 'LineString' && feature.geometry.type !== 'MultiLineString')) return []
    return [feature as Feature<LineString | MultiLineString>]
  })
  return { type: 'FeatureCollection', features }
}

function featureCollection(
  feature?: Feature<Geometry>,
): FeatureCollection<LineString | MultiLineString> {
  if (!feature || (feature.geometry.type !== 'LineString' && feature.geometry.type !== 'MultiLineString')) return EMPTY_LINES
  return { type: 'FeatureCollection', features: [feature as Feature<LineString | MultiLineString>] }
}

function mapLocations(
  scenario: ResilienceScenario,
  selectedOriginIds: string[],
  selectedGatewayIds: string[],
  records?: ResilienceAccessRecord[],
): ResilienceMapLocation[] {
  const access = new Map((records ?? []).map((record) => [record.origin.id, record.status]))
  const origins = scenario.origins.map((origin) => ({
    id: origin.id,
    label: origin.label,
    point: origin.point,
    kind: 'origin' as const,
    selected: selectedOriginIds.includes(origin.id),
    status: !selectedOriginIds.includes(origin.id)
      ? 'unknown' as const
      : access.get(origin.id) === 'stranded'
        ? 'stranded' as const
        : access.get(origin.id) === 'retained'
          ? 'reachable' as const
          : 'unknown' as const,
    detail: `${origin.address_count} municipal address points · ${origin.snap_distance_m.toFixed(0)} m centroid-to-node snap`,
  }))
  const gateways = scenario.gateway_groups.map((gateway) => ({
    id: gateway.id,
    label: gateway.label,
    point: gateway.point,
    kind: 'destination' as const,
    selected: selectedGatewayIds.includes(gateway.id),
    status: 'unknown' as const,
    detail: `${selectedGatewayIds.includes(gateway.id) ? 'Permitted OR-destination' : 'Not selected'} · reviewed outbound graph endpoint · not certified safe`,
  }))
  return [...origins, ...gateways]
}

function toggleId(values: string[], id: string): string[] {
  return values.includes(id) ? values.filter((value) => value !== id) : [...values, id].sort()
}

function sameIds(left: string[], right: string[]): boolean {
  return left.length === right.length && [...left].sort().every((value, index) => value === [...right].sort()[index])
}

function humanStatus(status: ResilienceResultStatus): string {
  if (status === 'verified_optimal') return 'Verified optimal under current graph assumptions'
  if (status === 'verified_unsat') return 'Verified infeasible under current graph assumptions'
  if (status === 'timeout') return 'Timeout — no feasibility conclusion'
  if (status === 'cancelled') return 'Cancelled — no feasibility conclusion'
  return 'Data or verification error'
}

function resilienceTerminalStatus(type: string): ResilienceResultStatus | undefined {
  if (type === 'verified_optimal' || type === 'verified_unsat' || type === 'timeout' || type === 'cancelled' || type === 'data_error') return type
  return undefined
}

function useModalDialog(
  open: boolean,
  dialogRef: RefObject<HTMLElement | null>,
  onClose: () => void,
) {
  const restoreFocusRef = useRef<HTMLElement | null>(null)
  useEffect(() => {
    if (!open) return
    restoreFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const dialog = dialogRef.current
    const focusableSelector = 'button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])'
    const frame = window.requestAnimationFrame(() => {
      const initialFocus = dialog?.querySelector<HTMLElement>('[data-dialog-close]')
      if (initialFocus) initialFocus.focus()
      else dialog?.focus()
    })
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onClose()
        return
      }
      if (event.key !== 'Tab' || !dialog) return
      const focusable = Array.from(dialog.querySelectorAll<HTMLElement>(focusableSelector))
        .filter((element) => !element.hasAttribute('disabled') && element.getClientRects().length > 0)
      if (!focusable.length) {
        event.preventDefault()
        dialog.focus()
        return
      }
      const first = focusable[0]
      const last = focusable.at(-1)
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last?.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first?.focus()
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      window.cancelAnimationFrame(frame)
      document.removeEventListener('keydown', handleKeyDown)
      restoreFocusRef.current?.focus()
      restoreFocusRef.current = null
    }
  }, [dialogRef, onClose, open])
}
