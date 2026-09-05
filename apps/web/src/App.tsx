import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { Feature, LineString } from 'geojson'
import {
  Accessibility,
  ArrowLeftRight,
  Ban,
  BookOpenText,
  Check,
  ChevronDown,
  CircleDot,
  CircleStop,
  ExternalLink,
  HeartPulse,
  Link2,
  LoaderCircle,
  MapPinned,
  Network,
  RotateCcw,
  Share2,
  Shield,
  Sprout,
  TriangleAlert,
} from 'lucide-react'
import { ApiError, cancelSolve, getScenario, streamSolve } from './api'
import { BudgetControl } from './components/BudgetControl'
import { CandidateInspector } from './components/CandidateInspector'
import { CompareDrawer } from './components/CompareDrawer'
import { ExperimentIndex } from './components/ExperimentIndex'
import { Legend } from './components/Legend'
import { MapView } from './components/MapView'
import { Methodology } from './components/Methodology'
import { PortalPairs } from './components/PortalPairs'
import { ResultPanel } from './components/ResultPanel'
import { ResilienceExperiment } from './components/ResilienceExperiment'
import { ServiceCoverageExperiment } from './components/ServiceCoverageExperiment'
import { SolverTimeline } from './components/SolverTimeline'
import { SolverComparisonPage } from './components/SolverComparisonPage'
import type {
  Alternative,
  Candidate,
  PortalPair,
  Scenario,
  ScenarioSettings,
  SolveEvent,
  SolveRequest,
  SolveResult,
  SolveStatus,
} from './types'
import { pairKey } from './types'
import { statusFromResult } from './resultStatus'
import { experienceFromUrl, replaceSettingsUrl, settingsFromUrl, settingsToSearch } from './urlState'
import type { Experience } from './urlState'

const DEFAULT_SETTINGS: ScenarioSettings = {
  budget: 4,
  selectedPairKeys: [],
  forced: [],
  locked: [],
  emergencyPermeable: true,
  objectiveMode: 'balanced',
  timeoutSeconds: 30,
}

const ACTIVE_STATUSES: SolveStatus[] = ['solving', 'candidate_found', 'counterexample_found', 'refining']

export function App() {
  const [activeExperience, setActiveExperience] = useState<Experience>(() => experienceFromUrl())
  const [resilienceMounted, setResilienceMounted] = useState(() => experienceFromUrl() === 'resilience')
  const [serviceCoverageMounted, setServiceCoverageMounted] = useState(() => experienceFromUrl() === 'coverage')
  const [showSolverGuide, setShowSolverGuide] = useState(false)
  const [scenario, setScenario] = useState<Scenario>()
  const [loadError, setLoadError] = useState<string>()
  const [reloadKey, setReloadKey] = useState(0)
  const [settings, setSettings] = useState<ScenarioSettings>(DEFAULT_SETTINGS)
  const [status, setStatus] = useState<SolveStatus>('idle')
  const [events, setEvents] = useState<SolveEvent[]>([])
  const [result, setResult] = useState<SolveResult>()
  const [liveCandidateIds, setLiveCandidateIds] = useState<string[]>([])
  const [counterexample, setCounterexample] = useState<Feature<LineString> | LineString | number[][]>()
  const [selectedCandidate, setSelectedCandidate] = useState<Candidate>()
  const [alternatives, setAlternatives] = useState<Alternative[]>([])
  const [nextPending, setNextPending] = useState(false)
  const [activeAlternativeId, setActiveAlternativeId] = useState('')
  const [comparisonId, setComparisonId] = useState<string>()
  const [viewMode, setViewMode] = useState<'before' | 'after'>('before')
  const [showAccess, setShowAccess] = useState(false)
  const [showMethod, setShowMethod] = useState(false)
  const [showCompare, setShowCompare] = useState(false)
  const [shareNotice, setShareNotice] = useState(false)
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const abortRef = useRef<AbortController | undefined>(undefined)
  const solveIdRef = useRef<string | undefined>(undefined)
  const terminalStatusRef = useRef<SolveStatus>('idle')
  const nextRunRef = useRef(false)
  const verifiedResultRef = useRef<SolveResult | undefined>(undefined)
  const alternativeNoticeRef = useRef(false)

  useEffect(() => {
    // Each experiment owns an independent frozen payload. Loading the sizeable
    // Kallio graph while somebody is opening Otaniemi coverage wastes work and
    // can contend with the allocation solver, so initialise it only on demand.
    if (activeExperience !== 'baseline' || scenario) return
    const controller = new AbortController()
    setLoadError(undefined)
    getScenario(controller.signal)
      .then((loaded) => {
        const allPairs = portalPairsForScenario(loaded)
        const defaults = loaded.default_portal_pairs.length ? loaded.default_portal_pairs : allPairs.slice(0, 2)
        const fallback = { ...DEFAULT_SETTINGS, selectedPairKeys: defaults.map(pairKey) }
        setScenario(loaded)
        setSettings(settingsFromUrl(fallback))
      })
      .catch((error: unknown) => {
        if ((error as Error).name !== 'AbortError') {
          setLoadError(error instanceof ApiError ? error.message : 'The frozen scenario could not be loaded.')
        }
      })
    return () => controller.abort()
  }, [activeExperience, reloadKey, scenario])

  useEffect(() => {
    if (scenario && activeExperience === 'baseline') replaceSettingsUrl(settings, activeExperience)
  }, [activeExperience, scenario, settings])

  const allPairs = useMemo(() => scenario ? portalPairsForScenario(scenario) : [], [scenario])
  const isSolving = ACTIVE_STATUSES.includes(status)
  const activeAlternative = alternatives.find((item) => item.id === activeAlternativeId)
  const displayedResult = activeAlternative?.result ?? result
  const displayedSelectedIds = displayedResult?.selected_intervention_ids ?? liveCandidateIds
  const comparisonIds = alternatives.find((item) => item.id === comparisonId)?.result.selected_intervention_ids ?? []
  const highlightedPortalIds = useMemo(() => {
    const byKey = new Map(allPairs.map((pair) => [pairKey(pair), pair]))
    return Array.from(new Set(settings.selectedPairKeys.flatMap((key) => {
      const pair = byKey.get(key)
      return pair ? [pair.a, pair.b] : []
    })))
  }, [allPairs, settings.selectedPairKeys])

  const updateSettings = useCallback((patch: Partial<ScenarioSettings>) => {
    setSettings((current) => ({ ...current, ...patch }))
  }, [])

  const resetOutcome = useCallback(() => {
    setStatus('idle')
    setEvents([])
    setResult(undefined)
    setLiveCandidateIds([])
    setCounterexample(undefined)
    setAlternatives([])
    setNextPending(false)
    setActiveAlternativeId('')
    setComparisonId(undefined)
    setShowCompare(false)
    setShowAccess(false)
    setViewMode('before')
    solveIdRef.current = undefined
    verifiedResultRef.current = undefined
    terminalStatusRef.current = 'idle'
  }, [])

  const navigateExperience = useCallback((next: Experience) => {
    const url = new URL(window.location.href)
    url.search = next === 'baseline' && !scenario
      ? '?experience=baseline'
      : settingsToSearch(settings, next)
    window.history.pushState(null, '', url)
    setShowSolverGuide(false)
    setShowMethod(false)
    setShowCompare(false)
    if (next === 'resilience') setResilienceMounted(true)
    if (next === 'coverage') setServiceCoverageMounted(true)
    setActiveExperience(next)
  }, [scenario, settings])

  useEffect(() => {
    const handlePopState = () => {
      const next = experienceFromUrl()
      setShowSolverGuide(false)
      if (next === 'resilience') setResilienceMounted(true)
      if (next === 'coverage') setServiceCoverageMounted(true)
      setActiveExperience(next)
      if (next === 'baseline' && scenario) {
        const defaults = scenario.default_portal_pairs.length
          ? scenario.default_portal_pairs
          : allPairs.slice(0, 2)
        setSettings(settingsFromUrl({
          ...DEFAULT_SETTINGS,
          selectedPairKeys: defaults.map(pairKey),
        }))
        resetOutcome()
      }
    }
    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [allPairs, resetOutcome, scenario])

  useEffect(() => {
    document.title = showSolverGuide
      ? 'How the solvers work · Geospatial Constraint Lab'
      : activeExperience === 'overview'
        ? 'Geospatial Constraint Lab'
        : activeExperience === 'resilience'
          ? 'Resilient access · Geospatial Constraint Lab'
          : activeExperience === 'coverage'
            ? 'Equitable service coverage · Geospatial Constraint Lab'
            : 'Four Planters · Geospatial Constraint Lab'
    const frame = window.requestAnimationFrame(() => {
      const selector = showSolverGuide
        ? '.solver-guide [data-page-heading]'
        : activeExperience === 'overview'
          ? '.experiment-index [data-page-heading]'
          : activeExperience === 'resilience'
            ? '.resilience-experiment [data-page-heading], .resilience-loading [data-page-heading]'
            : activeExperience === 'coverage'
              ? '.service-coverage-experiment [data-page-heading], .service-coverage-loading [data-page-heading]'
              : '.baseline-workspace [data-page-heading], .loading-screen [data-page-heading]'
      document.querySelector<HTMLElement>(selector)?.focus({ preventScroll: true })
      if ((activeExperience === 'resilience' || activeExperience === 'coverage') && !showSolverGuide) {
        window.dispatchEvent(new Event('resize'))
      }
    })
    return () => window.cancelAnimationFrame(frame)
  }, [activeExperience, showSolverGuide])

  const makeRequest = useCallback((next = false): SolveRequest | undefined => {
    if (!scenario) return undefined
    const pairByKey = new Map(allPairs.map((pair) => [pairKey(pair), pair]))
    return {
      scenario_id: scenario.id,
      budget: settings.budget,
      required_portal_pairs: settings.selectedPairKeys
        .map((key) => pairByKey.get(key))
        .filter((pair): pair is PortalPair => Boolean(pair))
        .map(({ a, b }) => ({ a, b })),
      forced_interventions: [...settings.forced].sort(),
      locked_open_streets: [...settings.locked].sort(),
      emergency_permeable: settings.emergencyPermeable,
      objective_mode: settings.objectiveMode,
      timeout_seconds: settings.timeoutSeconds,
      ...(next && solveIdRef.current ? { solve_id: solveIdRef.current } : {}),
    }
  }, [allPairs, scenario, settings])

  const handleSolveEvent = useCallback((event: SolveEvent) => {
    if (event.type !== 'complete') setEvents((current) => [...current, event])
    const solveId = typeof event.solve_id === 'string' ? event.solve_id : event.result?.solve_id
    if (solveId) solveIdRef.current = solveId
    if (event.selected_intervention_ids) setLiveCandidateIds(event.selected_intervention_ids)
    if (event.type === 'counterexample_found') {
      const route = routeFromEvent(event)
      if (route) setCounterexample(route)
      setStatus('counterexample_found')
    } else if (event.type === 'started') {
      setStatus('solving')
    } else if (event.type === 'candidate_found') {
      setStatus('candidate_found')
    } else if (event.type === 'refining' || event.type === 'candidate_rejected') {
      setStatus('refining')
    } else if (isTerminalType(event.type)) {
      const nextStatus = event.result
        ? statusFromResult(event.result)
        : (['timeout', 'cancelled', 'data_error'].includes(event.type) ? event.type as SolveStatus : 'data_error')
      terminalStatusRef.current = nextStatus
      setStatus(nextStatus)
    }
    if (event.result) {
      const nextStatus = statusFromResult(event.result)
      const verified = isVerifiedStatus(nextStatus)
      if (nextRunRef.current && !verified) {
        if (!alternativeNoticeRef.current) {
          alternativeNoticeRef.current = true
          setEvents((current) => [...current, { type: 'complete', message: 'No more equally optimal structural alternatives were found.' }])
        }
        if (verifiedResultRef.current) {
          setResult(verifiedResultRef.current)
          setStatus(statusFromResult(verifiedResultRef.current))
        }
        return
      }
      setResult(event.result)
      if (event.result.solve_id) solveIdRef.current = event.result.solve_id
      terminalStatusRef.current = nextStatus
      setStatus(nextStatus)
      setLiveCandidateIds(event.result.selected_intervention_ids)
      if (verified) verifiedResultRef.current = event.result
      setViewMode(verified ? 'after' : 'before')
      setCounterexample(undefined)
    }
  }, [])

  const solve = useCallback(async (next = false) => {
    const request = makeRequest(next)
    if (!request || (!request.required_portal_pairs.length && !next)) return
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    nextRunRef.current = next
    setNextPending(next)
    alternativeNoticeRef.current = false
    terminalStatusRef.current = 'solving'
    if (!next) {
      setEvents([])
      setResult(undefined)
      setSelectedCandidate(undefined)
      setAlternatives([])
      setActiveAlternativeId('')
      setComparisonId(undefined)
      setViewMode('before')
      setLiveCandidateIds(settings.forced)
    }
    setCounterexample(undefined)
    setStatus('solving')
    try {
      const final = await streamSolve(request, handleSolveEvent, controller.signal, next)
      if (final) {
        const finalStatus = statusFromResult(final)
        if (next && !isVerifiedStatus(finalStatus)) {
          if (verifiedResultRef.current) {
            setResult(verifiedResultRef.current)
            setStatus(statusFromResult(verifiedResultRef.current))
          }
          return
        }
        if (isVerifiedStatus(finalStatus)) {
          const alt: Alternative = {
            id: final.solve_id || `${next ? 'alternative' : 'solution'}-${Date.now()}`,
            label: next ? `Alternative ${alternatives.length + 1}` : 'Preferred solution',
            result: final,
          }
          setAlternatives((current) => {
            if (current.some((item) => item.result.selected_intervention_ids.join('|') === final.selected_intervention_ids.join('|'))) return current
            return [...current, alt]
          })
          setActiveAlternativeId(alt.id)
        }
        setResult(final)
        setStatus(finalStatus)
        if (isVerifiedStatus(finalStatus)) verifiedResultRef.current = final
        setViewMode(isVerifiedStatus(finalStatus) ? 'after' : 'before')
      } else if (terminalStatusRef.current === 'solving') {
        setStatus('data_error')
        setResult(indeterminateResult('data_error', 'The progress stream ended without a verified terminal result.', scenario?.snapshot_id ?? ''))
      }
    } catch (error: unknown) {
      if ((error as Error).name === 'AbortError') return
      const message = error instanceof ApiError ? error.message : 'The solver connection was interrupted.'
      terminalStatusRef.current = 'data_error'
      setStatus('data_error')
      setResult(indeterminateResult('data_error', message, scenario?.snapshot_id ?? ''))
    } finally {
      if (abortRef.current === controller) abortRef.current = undefined
      if (next) setNextPending(false)
    }
  }, [alternatives.length, handleSolveEvent, makeRequest, scenario?.snapshot_id, settings.forced])

  const cancel = useCallback(() => {
    const solveId = solveIdRef.current
    terminalStatusRef.current = 'cancelled'
    setStatus('cancelled')
    setResult(indeterminateResult('cancelled', 'The solve was stopped by the user. No feasibility conclusion was reached.', scenario?.snapshot_id ?? ''))
    setActiveAlternativeId('')
    setNextPending(false)
    abortRef.current?.abort()
    abortRef.current = undefined
    void cancelSolve(solveId).catch(() => {
      // The local abort still leaves the interface in a safe, explicitly cancelled state.
    })
  }, [scenario?.snapshot_id])

  useEffect(() => {
    if (isSolving && (activeExperience !== 'baseline' || showSolverGuide)) cancel()
  }, [activeExperience, cancel, isSolving, showSolverGuide])

  const reset = useCallback(() => {
    abortRef.current?.abort()
    resetOutcome()
    setSelectedCandidate(undefined)
    if (scenario) {
      const defaults = scenario.default_portal_pairs.length ? scenario.default_portal_pairs : allPairs.slice(0, 2)
      setSettings({ ...DEFAULT_SETTINGS, selectedPairKeys: defaults.map(pairKey) })
    }
  }, [allPairs, resetOutcome, scenario])

  const setConstraint = useCallback((kind: 'forced' | 'locked' | 'clear', candidate: Candidate) => {
    setSettings((current) => {
      const forced = current.forced.filter((id) => id !== candidate.id)
      const locked = current.locked.filter((id) => id !== candidate.id)
      if (kind === 'forced') forced.push(candidate.id)
      if (kind === 'locked') locked.push(candidate.id)
      return { ...current, forced, locked }
    })
    resetOutcome()
  }, [resetOutcome])

  const share = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href)
      setShareNotice(true)
      window.setTimeout(() => setShareNotice(false), 1800)
    } catch {
      setShareNotice(false)
    }
  }

  return (
    <div className={`app-shell app-shell--${activeExperience}`}>
      <header className="product-header">
        <a
          className="brand"
          href="/"
          aria-label="Geospatial Constraint Lab experiment index"
          onClick={(event) => {
            if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
            event.preventDefault()
            navigateExperience('overview')
          }}
        >
          <span className="lab-mark" aria-hidden="true"><Network size={18} /></span>
          <span>
            <strong>Geospatial Constraint Lab</strong>
            <small>{showSolverGuide ? 'Shared solver guide' : activeExperience === 'resilience' ? 'Experiment 02 · resilient access' : activeExperience === 'coverage' ? 'Experiment 03 · service allocation' : activeExperience === 'baseline' ? 'Experiment 01 · modal filters' : 'Experiment collection'}</small>
          </span>
        </a>
        <p>
          {showSolverGuide
            ? 'Which engine should answer which question—and why do these experiments use both?'
            : activeExperience === 'overview'
            ? 'Reproducible experiments in applying constraint solvers to geographic networks.'
            : activeExperience === 'resilience'
            ? 'Can selected address areas retain a private-car path to a designated network exit under explicit flood and roadworks assumptions?'
            : activeExperience === 'coverage'
            ? 'Which reviewed public facilities can serve every included population cell within explicit walking-distance and analytical-capacity limits?'
            : 'Can four small filters stop private-car through-routing while keeping every address connected?'}
        </p>
        <nav aria-label="Application information">
          {showSolverGuide ? (
            <button type="button" onClick={() => setShowSolverGuide(false)}>
              {activeExperience === 'overview' ? <MapPinned size={15} /> : <ArrowLeftRight size={15} />}
              {activeExperience === 'overview' ? 'Experiments' : 'Live experiment'}
            </button>
          ) : activeExperience === 'overview' ? (
            <button type="button" onClick={() => setShowSolverGuide(true)}>
              <Network size={15} /> How solvers work
            </button>
          ) : activeExperience === 'resilience' || activeExperience === 'coverage' ? (
            <>
              <button type="button" onClick={() => navigateExperience('overview')}>
                <MapPinned size={15} /> Experiments
              </button>
              <button type="button" onClick={() => setShowSolverGuide(true)}>
                <Network size={15} /> How solvers work
              </button>
            </>
          ) : (
            <>
              <button type="button" onClick={() => navigateExperience('overview')} disabled={isSolving}>
                <MapPinned size={15} /> Experiments
              </button>
              <button type="button" onClick={() => setShowSolverGuide(true)}><Network size={15} /> How solvers work</button>
              <button type="button" onClick={() => setShowMethod(true)}><BookOpenText size={15} /> Method</button>
              <button type="button" onClick={share}><Share2 size={15} /> {shareNotice ? 'Link copied' : 'Share'}</button>
            </>
          )}
        </nav>
      </header>

      {showSolverGuide && (
        <SolverComparisonPage
          onClose={() => setShowSolverGuide(false)}
          returnLabel={activeExperience === 'overview' ? 'Return to all experiments' : 'Return to the live experiment'}
        />
      )}
      {!showSolverGuide && activeExperience === 'overview' && (
        <ExperimentIndex
          onOpenModalFilters={() => navigateExperience('baseline')}
          onOpenResilientAccess={() => navigateExperience('resilience')}
          onOpenServiceCoverage={() => navigateExperience('coverage')}
          onOpenSolverGuide={() => setShowSolverGuide(true)}
        />
      )}
      {resilienceMounted && (
        <div className="experience-host" hidden={showSolverGuide || activeExperience !== 'resilience'}>
          <ResilienceExperiment active={activeExperience === 'resilience' && !showSolverGuide} />
        </div>
      )}
      {serviceCoverageMounted && (
        <div className="experience-host" hidden={showSolverGuide || activeExperience !== 'coverage'}>
          <ServiceCoverageExperiment active={activeExperience === 'coverage' && !showSolverGuide} />
        </div>
      )}
      {!showSolverGuide && activeExperience === 'baseline' && (!scenario ? (
        <LoadingScreen error={loadError} onRetry={() => setReloadKey((value) => value + 1)} />
      ) : (
      <main className="baseline-workspace">
        <aside className="instrument-panel" aria-label="Solver controls">
          <div className="panel-scroll">
            <section className="intro-block">
              <div className="scenario-kicker"><span className="live-dot" />Experiment 01 · frozen Kallio–Vallila</div>
              <h1 data-page-heading tabIndex={-1}>Close the shortcuts.<br />Keep the neighbourhood open.</h1>
              <p>Place mode-specific filters on local streets, then prove which boundary routes they cut.</p>
            </section>

            <BudgetControl value={settings.budget} onChange={(budget) => { updateSettings({ budget }); resetOutcome() }} disabled={isSolving} />

            <button
              type="button"
              className={`solve-button ${isSolving ? 'is-solving' : ''}`}
              onClick={() => isSolving ? cancel() : solve(false)}
              disabled={!isSolving && settings.selectedPairKeys.length === 0}
            >
              <span>{isSolving ? <CircleStop size={18} /> : <Sprout size={19} />}</span>
              <strong>{isSolving ? 'Cancel solve' : settings.budget === 4 ? 'Solve with four' : `Solve with ${settings.budget}`}</strong>
              {isSolving ? <LoaderCircle className="spin" size={18} /> : <span className="solve-button__arrow">→</span>}
            </button>
            {!settings.selectedPairKeys.length && <p className="control-warning"><TriangleAlert size={14} />Select at least one portal pair.</p>}

            {displayedResult && (!isSolving || nextPending) && (
              <ResultPanel
                result={displayedResult}
                status={nextPending ? statusFromResult(displayedResult) : status}
                candidates={scenario.candidates}
                onSelectCandidate={setSelectedCandidate}
                onNext={() => solve(true)}
                onCompare={() => setShowCompare(true)}
                onRaiseBudget={(budget) => { updateSettings({ budget: Math.min(8, Math.max(0, budget ?? settings.budget + 1)) }); resetOutcome() }}
                onUnlock={(candidateId) => { updateSettings({ locked: settings.locked.filter((id) => id !== candidateId) }); resetOutcome() }}
                onReleaseForced={(candidateId) => { updateSettings({ forced: settings.forced.filter((id) => id !== candidateId) }); resetOutcome() }}
                onRemovePortalPair={(pair) => { updateSettings({ selectedPairKeys: settings.selectedPairKeys.filter((key) => key !== pairKey(pair)) }); resetOutcome() }}
                onReviewAssumptions={() => setAdvancedOpen(true)}
                onOpenMethod={() => setShowMethod(true)}
                canUnlock={settings.locked.length > 0}
                alternativeCount={alternatives.length}
                nextPending={nextPending}
              />
            )}

            <SolverTimeline events={events} status={status} />

            <PortalPairs
              pairs={allPairs}
              portals={scenario.portals}
              selectedKeys={settings.selectedPairKeys}
              onChange={(selectedPairKeys) => { updateSettings({ selectedPairKeys }); resetOutcome() }}
              disabled={isSolving}
            />

            <details className="disclosure" open={advancedOpen} onToggle={(event) => setAdvancedOpen(event.currentTarget.open)}>
              <summary>
                <span className="summary-icon"><Shield size={15} /></span>
                <span><strong>Access & solver settings</strong><small>{settings.timeoutSeconds}s timeout · {settings.forced.length + settings.locked.length} street constraints</small></span>
                <ChevronDown className="disclosure__chevron" size={16} />
              </summary>
              <div className="assumption-list">
                <div className="assumption-static"><Accessibility size={16} /><span><strong>Walking & cycling unchanged in model</strong><small>Filters preserve these mode permissions; routes are not separately verified</small></span><Check size={15} /></div>
                <div className="assumption-static"><Ban size={16} /><span><strong>Endpoint-bias setbacks</strong><small>Filter marker midpoints: {scenario.terminal_zone.properties.setback_m} m from boundary · {scenario.portal_approach_zones.properties.setback_m} m from selectable portal crossings</small></span><Check size={15} /></div>
                <label className="assumption-toggle">
                  <HeartPulse size={16} />
                  <span><strong>Emergency-permeable filters</strong><small>Assume removable or unlockable treatment</small></span>
                  <input type="checkbox" checked={settings.emergencyPermeable} onChange={(event) => { updateSettings({ emergencyPermeable: event.target.checked }); resetOutcome() }} disabled={isSolving} />
                  <i aria-hidden="true" />
                </label>
                <div className="street-constraints"><span><CircleDot size={13} />{settings.forced.length} forced</span><span><Ban size={13} />{settings.locked.length} locked open</span><small>Select any candidate bar on the map to change its constraint.</small></div>
              </div>
              <div className="advanced-grid">
                <label>Objective
                  <select value={settings.objectiveMode} onChange={(event) => { updateSettings({ objectiveMode: event.target.value as ScenarioSettings['objectiveMode'] }); resetOutcome() }} disabled={isSolving}>
                    <option value="balanced">Balanced, lexicographic</option>
                    <option value="fewest">Fewest interventions</option>
                    <option value="access">Protect local access</option>
                  </select>
                </label>
                <label>Solver timeout
                  <select value={settings.timeoutSeconds} onChange={(event) => { updateSettings({ timeoutSeconds: Number(event.target.value) }); resetOutcome() }} disabled={isSolving}>
                    <option value="5">5 seconds</option>
                    <option value="10">10 seconds</option>
                    <option value="30">30 seconds</option>
                    <option value="60">60 seconds</option>
                    <option value="120">120 seconds</option>
                  </select>
                </label>
              </div>
            </details>

            <Legend
              boundarySetbackM={scenario.terminal_zone.properties.setback_m}
              portalSetbackM={scenario.portal_approach_zones.properties.setback_m}
            />

            <footer className="panel-footer">
              <button type="button" onClick={reset}><RotateCcw size={13} />Reset scenario</button>
              <span>{scenario.snapshot_id}</span>
              <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">© OpenStreetMap · ODbL <ExternalLink size={11} /></a>
            </footer>
          </div>
        </aside>

        <section className="map-region" aria-label="Network analysis map">
          <div className="view-toggle" role="group" aria-label="Network state">
            <button type="button" className={viewMode === 'before' ? 'is-active' : ''} onClick={() => setViewMode('before')} aria-pressed={viewMode === 'before'}>Before filters</button>
            <button type="button" className={viewMode === 'after' ? 'is-active' : ''} onClick={() => setViewMode('after')} aria-pressed={viewMode === 'after'} disabled={!displayedResult && !liveCandidateIds.length}>After filters</button>
          </div>
          <div className="portal-readout"><ArrowLeftRight size={14} />{settings.selectedPairKeys.length} route cuts requested</div>
          <MapView
            scenario={scenario}
            selectedIds={displayedSelectedIds}
            forcedIds={settings.forced}
            lockedIds={settings.locked}
            highlightedPortalIds={highlightedPortalIds}
            comparisonIds={comparisonIds}
            counterexample={counterexample}
            result={displayedResult}
            selectedCandidate={selectedCandidate}
            onCandidateSelect={setSelectedCandidate}
            viewMode={viewMode}
            showAccess={showAccess}
            onShowAccessChange={setShowAccess}
            solving={isSolving}
          />
          {selectedCandidate && (
            <CandidateInspector
              candidate={selectedCandidate}
              forced={settings.forced.includes(selectedCandidate.id)}
              locked={settings.locked.includes(selectedCandidate.id)}
              onForce={() => setConstraint('forced', selectedCandidate)}
              onLock={() => setConstraint('locked', selectedCandidate)}
              onClear={() => setConstraint('clear', selectedCandidate)}
              onClose={() => setSelectedCandidate(undefined)}
              disabled={isSolving}
            />
          )}
        </section>
      </main>
      ))}

      {showMethod && scenario && <><button className="sheet-backdrop" type="button" onClick={() => setShowMethod(false)} aria-label="Dismiss methods overlay" tabIndex={-1} /><Methodology scenario={scenario} onClose={() => setShowMethod(false)} /></>}
      {showCompare && scenario && (
        <>
          <button className="sheet-backdrop" type="button" onClick={() => setShowCompare(false)} aria-label="Dismiss comparison overlay" tabIndex={-1} />
          <CompareDrawer
            alternatives={alternatives}
            candidates={scenario.candidates}
            activeId={activeAlternativeId}
            compareId={comparisonId}
            onActivate={(id) => { setActiveAlternativeId(id); setResult(alternatives.find((item) => item.id === id)?.result); setComparisonId(undefined) }}
            onCompare={setComparisonId}
            onClose={() => { setShowCompare(false); setComparisonId(undefined) }}
          />
        </>
      )}
      {shareNotice && <div className="toast" role="status"><Link2 size={14} />Scenario link copied</div>}
    </div>
  )
}

function LoadingScreen({ error, onRetry }: { error?: string; onRetry: () => void }) {
  return (
    <main className={`loading-screen ${error ? 'has-error' : ''}`}>
      <span className="lab-mark lab-mark--large" aria-hidden="true"><Network size={23} /></span>
      {error ? (
        <>
          <TriangleAlert size={24} />
          <h1 data-page-heading tabIndex={-1}>Frozen scenario unavailable</h1>
          <p>{error} Start the solver service, then reconnect. No synthetic data has been substituted.</p>
          <button type="button" onClick={onRetry}>Retry connection</button>
        </>
      ) : (
        <>
          <LoaderCircle className="spin" size={22} />
          <h1 data-page-heading tabIndex={-1}>Loading modal-filter placement</h1>
          <p>Opening the frozen Kallio–Vallila street graph…</p>
        </>
      )}
    </main>
  )
}

function portalPairsForScenario(scenario: Scenario): PortalPair[] {
  const defaults = scenario.default_portal_pairs
  const pairs = new Map(defaults.map((pair) => [pairKey(pair), pair]))
  const additions: Array<{ pair: PortalPair; priority: number }> = []
  for (let i = 0; i < scenario.portals.length; i += 1) {
    for (let j = i + 1; j < scenario.portals.length; j += 1) {
      const a = scenario.portals[i]
      const b = scenario.portals[j]
      if (!a || !b) continue
      const sideA = cardinalSide(a.direction)
      const sideB = cardinalSide(b.direction)
      if (!sideA || !sideB || sideA === sideB) continue
      const pair = {
        a: a.id,
        b: b.id,
        label: `${a.direction || a.label} ↔ ${b.direction || b.label}`,
      }
      if (!pairs.has(pairKey(pair))) {
        const opposing = (sideA === 'N' && sideB === 'S') || (sideA === 'S' && sideB === 'N') ||
          (sideA === 'E' && sideB === 'W') || (sideA === 'W' && sideB === 'E')
        additions.push({ pair, priority: opposing ? 0 : 1 })
      }
    }
  }
  additions
    .sort((left, right) => left.priority - right.priority || left.pair.label.localeCompare(right.pair.label) || pairKey(left.pair).localeCompare(pairKey(right.pair)))
    .forEach(({ pair }) => {
      if (pairs.size < 12) pairs.set(pairKey(pair), pair)
    })
  return Array.from(pairs.values()).slice(0, 12)
}

function cardinalSide(direction: string): 'N' | 'E' | 'S' | 'W' | undefined {
  const normalized = direction.trim().toUpperCase()
  if (normalized.startsWith('N')) return 'N'
  if (normalized.startsWith('E')) return 'E'
  if (normalized.startsWith('S')) return 'S'
  if (normalized.startsWith('W')) return 'W'
  return undefined
}

function routeFromEvent(event: SolveEvent): Feature<LineString> | LineString | number[][] | undefined {
  const raw = event.route ?? event.route_geometry ?? event.geometry ?? event.path_geometry ?? event.coordinates
  if (!raw) return undefined
  if (Array.isArray(raw)) {
    if (raw.every((item) => Array.isArray(item) && item.length >= 2 && Number.isFinite(Number(item[0])))) return raw as number[][]
    return undefined
  }
  const value = raw as Feature<LineString> | LineString
  if (value.type === 'Feature' || value.type === 'LineString') return value
  return undefined
}

function isTerminalType(type: SolveEvent['type']): boolean {
  return ['verified_sat', 'verified_optimal', 'verified_unsat', 'timeout', 'cancelled', 'data_error'].includes(type)
}

function isVerifiedStatus(status: SolveStatus): boolean {
  return status === 'verified_sat' || status === 'verified_optimal'
}

function indeterminateResult(status: SolveStatus, explanation: string, snapshotId: string): SolveResult {
  return {
    status,
    selected_intervention_ids: [],
    objective_values: {},
    verification_status: status,
    address_access_summary: {},
    portal_connectivity_summary: {},
    local_detour_metrics: {},
    timing_ms: 0,
    iteration_count: 0,
    explanation,
    snapshot_id: snapshotId,
    solve_id: '',
  }
}
