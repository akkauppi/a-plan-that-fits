import { useEffect, useRef, useState } from 'react'
import { ArrowRight, Box, CheckCircle2, CircleHelp, Cpu, MapPin, RotateCcw } from 'lucide-react'
import type { Limits, Scenario, SolveRequest, SolveResult } from '../core/types.ts'
import { SolverClient } from '../solver/client.ts'
import type { ClientState } from '../solver/client.ts'
import { MapView } from './MapView.tsx'
import { CandidateExplanation } from './CandidateExplanation.tsx'
import { comparisonConclusion } from './comparison.ts'

const chapters = ['The question', 'Build a plan', 'Test resilience', 'Ask the solver', 'Reflect']
type Run = { label: string; request: SolveRequest; scope: 'selection' | 'starter' | 'all' }
type Comparison = { label: string; request: SolveRequest; stage: 'z3' | 'exhaustive' | 'done'; z3?: SolveResult; exhaustive?: SolveResult }
const number = (value: number) => value.toLocaleString('en-GB')

export function App() {
  const [scenario, setScenario] = useState<Scenario>()
  const [loadError, setLoadError] = useState('')
  useEffect(() => {
    const controller = new AbortController()
    fetch(`${import.meta.env.BASE_URL}data/scenario.json`, { signal: controller.signal }).then(response => {
      if (!response.ok) throw new Error(`Scenario could not load (HTTP ${response.status}).`)
      return response.json() as Promise<Scenario>
    }).then(setScenario).catch(error => { if (!controller.signal.aborted) setLoadError(String(error)) })
    return () => controller.abort()
  }, [])
  if (!scenario) return <main className="loading-page"><span className="brand"><MapPin size={22} /> A plan that fits</span><h1>{loadError ? 'The tour could not load.' : 'Opening the neighbourhood…'}</h1><p>{loadError || 'Loading the frozen geography. No planning API or account is needed.'}</p>{loadError && <button onClick={() => location.reload()}>Reload</button>}</main>
  return <Tour scenario={scenario} />
}

function Tour({ scenario }: { scenario: Scenario }) {
  const [chapter, setChapter] = useState(0)
  const [selectedLockers, setSelectedLockers] = useState<string[]>(scenario.starterLockerIds)
  const [selectedDepots, setSelectedDepots] = useState<string[]>([])
  const [cellId, setCellId] = useState(scenario.cells[0].id)
  const [limits, setLimits] = useState<Limits>(scenario.defaults)
  const [engine, setEngine] = useState<ClientState>({ phase: 'loading' })
  const [exhaustiveEngine, setExhaustiveEngine] = useState<ClientState>({ phase: 'loading' })
  const [run, setRun] = useState<Run>()
  const [comparison, setComparison] = useState<Comparison>()
  const [comparisonCase, setComparisonCase] = useState<'feasible' | 'impossible'>('feasible')
  const [methodOpen, setMethodOpen] = useState(false)
  const client = useRef<SolverClient | undefined>(undefined)
  const exhaustiveClient = useRef<SolverClient | undefined>(undefined)
  const heading = useRef<HTMLHeadingElement>(null)
  const methodButton = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (!window.crossOriginIsolated || typeof SharedArrayBuffer === 'undefined') {
      setEngine({ phase: 'error', message: 'The browser needs site isolation to run Z3. On the first visit this page reloads once to enable it. If this message remains, use HTTPS (or localhost), allow this site’s service worker, then reload. There is no server-side fallback.' })
      return
    }
    const instance = new SolverClient(scenario, () => new Worker(new URL(`${import.meta.env.BASE_URL}runtime/solver-worker.js`, document.baseURI)), setEngine)
    const exhaustive = new SolverClient(scenario, () => new Worker(new URL(`${import.meta.env.BASE_URL}runtime/exhaustive-worker.js`, document.baseURI)), setExhaustiveEngine, 'Exhaustive search')
    client.current = instance
    exhaustiveClient.current = exhaustive
    return () => { instance.dispose(); exhaustive.dispose(); client.current = undefined; exhaustiveClient.current = undefined }
  }, [scenario])
  const z3Busy = engine.phase === 'solving' || engine.phase === 'verifying'
  const exhaustiveBusy = exhaustiveEngine.phase === 'solving' || exhaustiveEngine.phase === 'verifying'
  const busy = z3Busy || exhaustiveBusy
  const result = run ? engine.result : undefined
  const plan = result?.status === 'feasible' ? result.plan : comparison?.z3?.status === 'feasible' ? comparison.z3.plan : undefined
  const total = scenario.cells.reduce((sum, cell) => sum + cell.parcels, 0)
  const ready = engine.phase === 'ready'
  function go(next: number) {
    if (z3Busy) client.current?.cancel()
    if (exhaustiveBusy) exhaustiveClient.current?.cancel()
    setChapter(next); setRun(undefined); setComparison(undefined); setLimits(scenario.defaults); setSelectedLockers(next === 1 ? [] : scenario.starterLockerIds); setSelectedDepots([])
    requestAnimationFrame(() => heading.current?.focus())
  }
  function solve(label: string, scope: Run['scope'], overrides: Partial<SolveRequest> = {}) {
    const request = { ...scenario.defaults, ...overrides, timeoutMs: 30000 }
    if (client.current?.solve(request)) { setComparison(undefined); setRun({ label, request, scope }) }
  }
  function compareSolvers() {
    const request = { ...scenario.defaults, ...(comparisonCase === 'impossible' ? { maxDepots: 3 } : {}), timeoutMs: 30000 }
    const label = comparisonCase === 'impossible' ? 'Can three depots survive an outage?' : 'Can a network with up to four depots survive an outage?'
    if (client.current?.solve(request)) { setRun(undefined); setComparison({ label, request, stage: 'z3' }) }
  }
  function toggleDepot(id: string) {
    if (busy || chapter !== 1) return
    setRun(undefined); setComparison(undefined)
    setSelectedDepots(current => current.includes(id) ? current.filter(value => value !== id) : current.length < scenario.defaults.maxDepots ? [...current, id] : current)
  }
  function toggleLocker(id: string) {
    if (busy || chapter !== 1) return
    setRun(undefined); setComparison(undefined)
    setSelectedLockers(current => current.includes(id) ? current.filter(value => value !== id) : current.length < scenario.defaults.maxLockers ? [...current, id] : current)
  }
  function resetGame() {
    if (busy) return
    setRun(undefined); setComparison(undefined); setSelectedLockers([]); setSelectedDepots([])
  }
  const uncoveredCells = scenario.cells.filter(cell => !scenario.walking.some(pair => pair.cellId === cell.id && selectedLockers.includes(pair.lockerId)))
  const requiredDepotChoices = (scenario.defaults.depotOutageTolerance ?? 0) + 1
  const lockersWithoutBackup = selectedLockers.filter(lockerId => scenario.flights.filter(pair => pair.lockerId === lockerId && selectedDepots.includes(pair.depotId) && pair.returnDistanceMm <= scenario.defaults.flightLimitMm).length < requiredDepotChoices)
  const supplyPreviewReady = selectedLockers.length > 0 && selectedDepots.length >= requiredDepotChoices && lockersWithoutBackup.length === 0
  const siteCountsReady = selectedLockers.length === scenario.defaults.maxLockers && selectedDepots.length === scenario.defaults.maxDepots
  useEffect(() => {
    if (chapter === 1 && run?.scope === 'all' && result?.status === 'feasible') {
      setSelectedLockers(result.plan.lockerIds); setSelectedDepots(result.plan.depotIds)
    }
  }, [chapter, result, run])
  useEffect(() => {
    if (comparison?.stage !== 'z3' || engine.phase !== 'ready' || !engine.result) return
    const z3 = engine.result
    if (exhaustiveClient.current?.solve(comparison.request)) setComparison({ ...comparison, stage: 'exhaustive', z3 })
    else setComparison({ ...comparison, stage: 'done', z3, exhaustive: { status: 'error', message: 'Exhaustive worker was not ready.', elapsedMs: 0 } })
  }, [comparison, engine])
  useEffect(() => {
    if (comparison?.stage === 'exhaustive' && exhaustiveEngine.phase === 'ready' && exhaustiveEngine.result) setComparison({ ...comparison, stage: 'done', exhaustive: exhaustiveEngine.result })
  }, [comparison, exhaustiveEngine])
  const title = [
    'What makes a plan work?', 'Build a resilient plan.', 'What changes when a depot closes?',
    'What can a solver tell us?', 'Change a rule. Explain the answer.',
  ][chapter]
  return <div className="app-shell">
    <header className="topbar"><a className="brand" href={import.meta.env.BASE_URL}><MapPin size={22} strokeWidth={2.5} /> A plan that fits</a><span className="project-description">An exploration of planning constraints</span><button ref={methodButton} className="text-button" onClick={() => setMethodOpen(true)}><CircleHelp size={17} /> How it works</button></header>
    <main className="workspace">
      <MapView scenario={scenario} plan={plan} selectedLockers={chapter < 3 ? selectedLockers : []} selectedDepots={selectedDepots} cellId={cellId} onCell={setCellId} onLocker={toggleLocker} onDepot={toggleDepot} canChooseLockers={chapter === 1 && !busy} canChooseDepots={chapter === 1 && !busy} maxSelectedLockers={scenario.defaults.maxLockers} maxSelectedDepots={scenario.defaults.maxDepots} gameMode={chapter === 1} showStarterAssignments={chapter === 0 || chapter === 2} />
      <aside className="story-panel" aria-label="Self-guided solver tour">
        <nav className="chapter-nav" aria-label="Tour chapters">{chapters.map((name, i) => <button key={name} aria-current={i === chapter ? 'step' : undefined} aria-label={`${i + 1}. ${name}`} onClick={() => go(i)}><span>{i + 1}</span><span className="chapter-name">{name}</span></button>)}</nav>
        <div className="story-content">
          <p className="eyebrow">DRONE-SUPPLIED PARCEL LOCKERS · {chapter + 1} / 5</p>
          <h1 ref={heading} tabIndex={-1}>{title}</h1>
          {chapter === 0 && <>
            <p className="lead">Can a map-based planning game help us understand rules that must work together—and the role a solver could play? Explore that question through a hypothetical parcel-delivery network.</p>
            <p className="study-note"><strong>Exploratory prototype.</strong> This tour is a starting point for studying understanding. Its learning benefits have not yet been evaluated.</p>
            <div className="delivery-chain" aria-label="Depot supplies locker by drone; resident walks to locker"><span>◇ Depot</span><span className="chain-link">drone →</span><span>▣ Locker</span><span className="chain-link">← walk</span><span>Resident</span></div>
            <section className="solver-intro" aria-label="What is a constraint solver?"><h2>State the rules. Explore what follows.</h2><p>A <strong>constraint</strong> is a rule that must be met, such as “no collection walk longer than 500 m”. A <strong>constraint solver</strong> searches for choices that satisfy every rule together—or can prove that none work within the model.</p><p>Here we use <strong>Z3</strong>, a general-purpose solver. Geographic calculations supply allowed connections; Z3 checks how choices can fit together. A result helps examine the stated rules, not decide which rules a community should adopt.</p><a href="https://developers.google.com/optimization/cp" target="_blank" rel="noreferrer">An introduction to constraint solving ↗</a></section>
            <RuleCard limits={scenario.defaults} />
            <button className="primary" onClick={() => go(1)}>Try a plan <ArrowRight size={18} /></button>
            <p className="quiet">Predict, check, then explain. No coding is needed, and you can skip ahead at any time.</p>
            <p className="data-note">Real geography; a made-up planning brief. {number(scenario.cells.reduce((sum, cell) => sum + cell.population, 0))} residents in 33 published population cells become <strong>{total} illustrative parcels/day</strong>. We represent each cell by one point, not every home.</p>
            <CandidateExplanation scenario={scenario} />
            <p className="interaction-note"><strong>Step 1 is for inspection.</strong> Select a population cell or an open locker to trace a possible collection journey. The prepared lockers only make routes inspectable; the planning game starts empty.</p>
          </>}
          {chapter === 1 && <>
            <p className="lead">Start empty. Choose exactly <strong>{scenario.defaults.maxLockers} lockers</strong> and <strong>{scenario.defaults.maxDepots} depots</strong>. Every cell needs a walk of at most 500 m. Every locker needs a second depot in range so one can fail.</p>
            <p className="interaction-note"><strong>You can build on the map.</strong> Click any locker circle or depot label to toggle it; the buttons below provide the same controls. Coral rings expose candidates without enough selected depots in exact 2 km return-flight range.</p>
            <p className="reflection-prompt"><strong>Before checking:</strong> which rule could still fail even when every cell has a nearby locker and every locker has a backup depot?</p>
            <fieldset disabled={busy} className="site-picker locker-picker"><legend>Lockers · {selectedLockers.length}/{scenario.defaults.maxLockers} selected</legend>{scenario.lockers.map(locker => <button key={locker.id} aria-label={`Locker ${locker.id}`} aria-pressed={selectedLockers.includes(locker.id)} disabled={!selectedLockers.includes(locker.id) && selectedLockers.length === scenario.defaults.maxLockers} onClick={() => toggleLocker(locker.id)}>{locker.id}</button>)}</fieldset>
            <fieldset disabled={busy} className="site-picker depot-picker"><legend>Depots · {selectedDepots.length}/{scenario.defaults.maxDepots} selected</legend>{scenario.depots.map(depot => <button key={depot.id} aria-pressed={selectedDepots.includes(depot.id)} disabled={!selectedDepots.includes(depot.id) && selectedDepots.length === scenario.defaults.maxDepots} onClick={() => toggleDepot(depot.id)}>◇ {depot.id}</button>)}</fieldset>
            <div className="game-checks" aria-label="Quick map checks" aria-live="polite">
              <p className={uncoveredCells.length ? 'warning' : 'pass'}><span>{uncoveredCells.length ? '!' : '✓'}</span><strong>{uncoveredCells.length ? `${uncoveredCells.length} cells have no selected locker within 500 m` : 'Every cell has a selected locker within 500 m'}</strong></p>
              <p className={supplyPreviewReady ? 'pass' : 'warning'}><span>{supplyPreviewReady ? '✓' : '!'}</span><strong>{!selectedLockers.length ? 'Choose lockers to check backup reach' : selectedDepots.length < requiredDepotChoices ? 'Choose at least two depots to check backup reach' : lockersWithoutBackup.length ? `${lockersWithoutBackup.length} selected lockers lack a second depot in range` : 'Every selected locker has a backup depot in range'}</strong></p>
              <p className={siteCountsReady ? 'pass' : 'warning'}><span>{siteCountsReady ? '✓' : '!'}</span><strong>{siteCountsReady ? 'Site budgets filled' : `Select exactly ${scenario.defaults.maxLockers} lockers and ${scenario.defaults.maxDepots} depots`}</strong></p>
            </div>
            <p className="quiet">These quick checks show necessary geography only. They do not prove that every normal and outage assignment fits the shared depot capacities.</p>
            <button className="primary" disabled={!ready || !siteCountsReady} onClick={() => solve('Your ten lockers and four depots', 'selection', { fixedLockerIds: selectedLockers, fixedDepotIds: selectedDepots })}>Check my plan with Z3 <Cpu size={18} /></button>
            <div className="game-actions"><button onClick={resetGame}>Clear my plan</button><button disabled={!ready} onClick={() => solve('Z3 chose all sites', 'all')}>Let Z3 find a plan</button></div>
            <p className="quiet">Checking uses exactly your selected sites. “Let Z3 find a plan” removes those choices and asks the solver to select all locations.</p>
          </>}
          {chapter === 2 && <>
            <p className="lead">Resilience adds a question: can the remaining depots take over when one closes? Residents keep their assigned lockers; supplies may be reassigned in each outage, within the same range and capacity limits.</p>
            <div className="conflict-chain"><p><b>Normal day</b><span>plus</span><strong>4 outage cases</strong></p><p><b>Each locker</b><span>needs</span><strong>a backup supplier</strong></p><p><b>871 parcels</b><span>must rebalance under</span><strong>shared capacities</strong></p></div>
            <p>Predict what happens if the depot budget falls from four to three. Which condition might become impossible to meet?</p>
            <button className="primary" disabled={!ready} onClick={() => solve('Three depots, one may fail', 'all', { maxDepots: 3 })}>Check the three-depot case <Cpu size={18} /></button>
            <p className="quiet">UNSAT means no choice among these 24 locker and six depot candidates satisfies all the stated rules. It is not a claim about every possible real location.</p>
            <details className="geographic-explanation"><summary>What the geography already tells us</summary><p>In this snapshot, there are 20 ways to choose three depots. For each choice, keep only lockers with at least two selected depots in range. Even allowing all those lockers to open, the best choice covers only <strong>27 of 33 cells</strong>.</p><p>This simple check already rules out a resilient three-depot network, before capacity is considered. Z3 can check the full model too; this case does not require a general-purpose solver to establish impossibility.</p></details>
          </>}
          {chapter === 3 && <>
            <p className="lead">Restore four depots. Let the solver choose sites, collection assignments, normal suppliers and a complete reassignment for every depot outage.</p>
            <RuleCard limits={scenario.defaults} />
            <p>Z3 answers a precise question: <strong>does any network satisfy every rule?</strong> A feasible answer gives assignments to inspect. An impossibility result means the candidate set and rules cannot work together. A timeout gives no conclusion.</p>
            <button className="primary" disabled={!ready} onClick={() => solve('Joint resilient network', 'all')}>Find a resilient network <Cpu size={18} /></button>
            <p className="quiet">A feasible network, not a claim that it is cheapest or best. We check the returned routes and loads again in separate JavaScript code.</p>
            <p className="reflection-prompt"><strong>Inspect the answer:</strong> what did the solver choose, and what assumptions did we choose for it?</p>
            <details className="solver-comparison-intro" data-testid="comparison-options"><summary>Optional: compare two solving methods</summary><p>Do two independent implementations reach the same feasibility conclusion? Z3 uses logical and arithmetic constraints. Exhaustive JavaScript search explicitly tries choices and rules out impossible branches.</p><label>Question to compare<select aria-label="Question to compare" disabled={busy} value={comparisonCase} onChange={event => { setComparisonCase(event.target.value as 'feasible' | 'impossible'); setComparison(undefined) }}><option value="feasible">Up to four depots, one may fail</option><option value="impossible">Up to three depots, one may fail</option></select></label><button disabled={!ready || exhaustiveEngine.phase !== 'ready'} onClick={compareSolvers}>Check with both methods</button>{exhaustiveEngine.phase === 'error' && <p role="alert">The brute-force worker could not start: {exhaustiveEngine.message}</p>}<p className="quiet">Both receive identical rules and use the same independent checker for feasible plans. Agreement is an implementation check, not evidence that the planning assumptions are realistic or that one method is generally faster.</p>{comparison && <ComparisonPanel comparison={comparison} />}</details>
          </>}
          {chapter === 4 && <>
            <p className="lead">Predict the effect of a change, then check it. The walking limit stays at 500 m throughout this exercise. Each answer still applies only to these candidates and the chosen rules.</p>
            <div className="experiments">
              <button disabled={!ready} onClick={() => solve('Three depots, normal operation only', 'all', { maxDepots: 3, depotOutageTolerance: 0 })}><strong>Remove the outage rule.</strong><span>Up to 3 depots · normal operation only</span><ArrowRight size={18} /></button>
              <button disabled={!ready} onClick={() => solve('Four depots, one may fail', 'all')}><strong>Restore the fourth depot.</strong><span>Up to 4 depots · any one may fail</span><ArrowRight size={18} /></button>
              <button disabled={!ready} onClick={() => solve('Nine lockers, one depot may fail', 'all', { maxLockers: 9 })}><strong>Can nine lockers work?</strong><span>Up to 9 lockers · resilience retained</span><ArrowRight size={18} /></button>
            </div>
            <details className="custom-rules"><summary>Try your own combination</summary><p>All site choices are free here. Capacity is shared, and each cell’s demand stays together.</p><fieldset disabled={busy}>
              <label>Locker budget <input type="number" min={0} max={scenario.lockers.length} value={limits.maxLockers} onChange={e => { setLimits({ ...limits, maxLockers: Number(e.target.value) }); setRun(undefined) }} /></label>
              <label>Depot budget <input type="number" min={0} max={scenario.depots.length} value={limits.maxDepots} onChange={e => { setLimits({ ...limits, maxDepots: Number(e.target.value) }); setRun(undefined) }} /></label>
              <label>Depot outage rule <select value={limits.depotOutageTolerance ?? 0} onChange={e => { setLimits({ ...limits, depotOutageTolerance: Number(e.target.value) }); setRun(undefined) }}><option value={1}>Any one may fail</option><option value={0}>Normal operation only</option></select></label>
              <label>Return-flight range <select value={limits.flightLimitMm} onChange={e => { setLimits({ ...limits, flightLimitMm: Number(e.target.value) }); setRun(undefined) }}><option value={2000000}>2 km</option><option value={2400000}>2.4 km</option></select></label>
              <label>Parcels per locker / day <input type="number" min={0} max={10000} value={limits.lockerCapacity} onChange={e => { setLimits({ ...limits, lockerCapacity: Number(e.target.value) }); setRun(undefined) }} /></label>
              <label>Parcels per depot / day <input type="number" min={0} max={10000} value={limits.depotCapacity} onChange={e => { setLimits({ ...limits, depotCapacity: Number(e.target.value) }); setRun(undefined) }} /></label>
            </fieldset><button disabled={!ready} onClick={() => solve('Your rules, all sites free', 'all', limits)}>Check these rules</button></details>
            <section className="reflection" aria-labelledby="reflection-title"><h2 id="reflection-title">What can you explain now?</h2><ul><li>Why can nearby connections still fail to form a feasible network?</li><li>What does a feasible answer leave undecided?</li><li>Could changing the candidate sites change an impossibility result?</li></ul><p className="quiet">These are prompts for your own reflection or a colleague discussion. The app does not record responses.</p></section>
          </>}

          <div className="engine-status" role="status" aria-live="polite"><span className={`status-dot ${ready ? 'ready' : ''}`} />{engine.phase === 'loading' ? 'Loading Z3 into your browser… (about 34 MB on first visit)' : engine.phase === 'error' ? engine.message : z3Busy ? `${engine.phase === 'verifying' ? 'Independently checking Z3’s result' : 'Z3 is checking the rules'}…` : exhaustiveBusy ? `${exhaustiveEngine.phase === 'verifying' ? 'Independently checking brute-force search’s result' : 'Brute-force JavaScript is checking every remaining branch'}…` : 'Z3 ready · runs locally in this browser'}</div>
          {busy && <button className="cancel" onClick={() => { if (z3Busy) client.current?.cancel(); if (exhaustiveBusy) exhaustiveClient.current?.cancel(); setComparison(undefined) }}>Cancel calculation</button>}
          {result && run && <Result result={result} run={run} />}
          {chapter > 0 && chapter < 4 && <button className="next-button" onClick={() => go(chapter + 1)}>{['', 'Examine a depot outage', 'Ask the solver to choose', 'Explore and reflect'][chapter]} <ArrowRight size={17} /></button>}
          {chapter === 4 && <button className="text-button restart" onClick={() => go(0)}><RotateCcw size={16} /> Restart the tour</button>}
        </div>
        <footer className="story-footer">An exploratory learning prototype. Results apply to this model, not real site approvals.</footer>
      </aside>
    </main>
    {methodOpen && <MethodDialog scenario={scenario} onClose={() => { setMethodOpen(false); requestAnimationFrame(() => methodButton.current?.focus()) }} />}
  </div>
}

function RuleCard({ limits }: { limits: Limits }) {
  return <div className="rule-card"><div><strong>500 m</strong><span>maximum walk along paths</span></div><div><strong>{limits.maxLockers} + {limits.maxDepots}</strong><span>lockers + depots, at most</span></div><div><strong>{limits.flightLimitMm / 1000000} km</strong><span>maximum return flight</span></div><div><strong>{limits.depotOutageTolerance ? '1 outage' : 'normal only'}</strong><span>{limits.depotOutageTolerance ? 'every selected depot tested' : 'no failure case'}</span></div></div>
}

function ComparisonPanel({ comparison }: { comparison: Comparison }) {
  const answer = (result?: SolveResult, waiting = false) => waiting ? 'Waiting' : !result ? 'Checking…' : result.status === 'feasible' ? 'Plan found' : result.status === 'unsat' ? 'Proved impossible' : result.status === 'timeout' ? 'No conclusion' : result.status === 'cancelled' ? 'Cancelled' : 'Error'
  const conclusion = comparison.stage === 'done' && comparison.z3 && comparison.exhaustive ? comparisonConclusion(comparison.z3.status, comparison.exhaustive.status) : undefined
  const stats = comparison.exhaustive?.search
  return <section className="solver-comparison" aria-label="Feasibility cross-check" aria-live="polite" data-testid="solver-comparison">
    <table><caption>{comparison.label}</caption><thead><tr><th>Method</th><th>Answer</th></tr></thead><tbody>
      <tr><th>Z3</th><td>{answer(comparison.z3)}</td></tr>
      <tr><th>Brute-force JS</th><td>{answer(comparison.exhaustive, comparison.stage === 'z3')}</td></tr>
    </tbody></table>
    {conclusion && <p className={`comparison-${conclusion.kind}`}>{conclusion.message}</p>}
    <p className="quiet">Scope: all candidates available; up to {comparison.request.maxLockers} lockers and {comparison.request.maxDepots} depots; 500 m walking; {comparison.request.flightLimitMm / 1000000} km return flight; {comparison.request.lockerCapacity}/{comparison.request.depotCapacity} parcels per locker/depot per day; any one selected depot may fail.</p>
    <details data-testid="comparison-diagnostics"><summary>Timing and search details</summary>
      <table><caption>Illustrative warm-run measurements</caption><thead><tr><th>Method</th><th>Elapsed time</th></tr></thead><tbody>
        <tr><th>Z3</th><td>{comparison.z3 ? `${comparison.z3.elapsedMs} ms` : '—'}</td></tr>
        <tr><th>Brute-force JS</th><td>{comparison.exhaustive ? `${comparison.exhaustive.elapsedMs} ms` : '—'}</td></tr>
      </tbody></table>
      {stats && <p className="search-receipt">Brute-force search inspected {number(stats.lockerSetsChecked)} locker sets, {number(stats.siteSelectionsChecked)} complete site selections, {number(stats.assignmentBranchesVisited)} collection-assignment branches and {number(stats.supplyBranchesVisited)} supply branches before stopping.</p>}
      {stats && stats.lockerSetsChecked > 0 && stats.siteSelectionsChecked === 0 && <p className="search-receipt">Every inspected locker set was eliminated by walking coverage or locker capacity before depot choices were needed.</p>}
      <p>Both methods run sequentially in warm workers. Elapsed time includes scenario validation, search or model construction, and checking feasible answers. Download and worker initialization are excluded; each search has a 30-second limit.</p>
      <p>These measurements concern one structured case and two implementations. Search order, encoding, browser and hardware affect them. A simple check of 20 depot triples already establishes the three-depot impossibility; millions of possible site combinations do not establish computational difficulty.</p>
    </details>
  </section>
}

function Result({ result, run }: { result: SolveResult; run: Run }) {
  return <section className={`result ${result.status}`} aria-label="Solver result" aria-live="polite" data-testid="solver-result" data-status={result.status}>
    <span className="eyebrow">{run.label}</span>
    {result.status === 'feasible' ? <>
      <h2><CheckCircle2 size={22} /> {run.scope === 'selection' ? 'You found a plan that fits.' : 'A network fits the stated rules.'}</h2>
      <p>{result.plan.lockerIds.length} lockers · {result.plan.depotIds.length} depots · all {result.verification.parcelTotal} parcels assigned.</p>
      <p className="verification">Z3 found the hidden assignments; separate JavaScript verified {result.verification.routesChecked} walks ≤ 500 m, all return flights ≤ {run.request.flightLimitMm / 1000000} km, every daily capacity{run.request.depotOutageTolerance ? ` and ${result.plan.outagePlans?.length ?? 0} complete depot-outage plans` : ''}.</p>
      <p>A feasible answer is one example that satisfies the model. It does not establish the best locations or validate the assumptions.</p>
      <details><summary>Inspect the assignments and loads</summary><p>Lockers: {result.plan.lockerIds.join(', ')}. Select a population cell on the map to trace its journey.</p><table><caption>Daily parcel loads</caption><thead><tr><th>Locker</th><th>Parcels</th><th>Supplier</th></tr></thead><tbody>{result.plan.lockerIds.map(id => <tr key={id}><td>{id}</td><td>{result.verification.lockerLoads[id]} / {run.request.lockerCapacity}</td><td>{result.plan.supplies.find(s => s.lockerId === id)!.depotId}</td></tr>)}</tbody></table><p>{result.plan.depotIds.map(id => `${id}: ${result.verification.depotLoads[id]} / ${run.request.depotCapacity}`).join(' · ')}</p></details>
      {run.request.depotOutageTolerance === 1 && <details><summary>Inspect the depot-outage checks</summary>{result.plan.outagePlans?.map(outage => <p key={outage.unavailableDepotId}><strong>{outage.unavailableDepotId} unavailable:</strong> {result.plan.depotIds.filter(id => id !== outage.unavailableDepotId).map(id => `${id} ${result.verification.outageDepotLoads[outage.unavailableDepotId]?.[id] ?? 0}/${run.request.depotCapacity}`).join(' · ')}</p>)}</details>}
    </> : result.status === 'unsat' ? <>
      <h2>No network fits these rules.</h2>
      <p>{run.scope === 'selection' ? 'This exact site selection does not work. That alone says nothing about other selections.' : run.scope === 'starter' ? 'No assignment works while keeping exactly the prepared lockers and the stated limits.' : 'No combination of the candidate lockers and depots works under these limits.'}</p>
      <details><summary>Which rules conflict?</summary><p>Z3 returned this conflicting set of rule groups. It is not necessarily the smallest set, and is not a ranked list of repairs.</p><ul>{result.rules.map(rule => <li key={rule.id}>{rule.label}</li>)}</ul></details>
    </> : <><h2>{result.status === 'cancelled' ? 'Calculation cancelled.' : result.status === 'timeout' ? 'No conclusion yet.' : 'The calculation could not be verified.'}</h2><p>{result.message}</p></>}
    <p className="result-receipt">Limits: {run.request.maxLockers} lockers · {run.request.maxDepots} depots · 500 m walking · {run.request.flightLimitMm / 1000000} km return · {run.request.lockerCapacity}/{run.request.depotCapacity} parcels per locker/depot per day · {run.request.depotOutageTolerance ? 'one depot may fail' : 'normal operation only'}.</p>
  </section>
}

function MethodDialog({ scenario, onClose }: { scenario: Scenario; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => { const element = dialog.current!; element.showModal(); return () => element.close() }, [])
  return <dialog ref={dialog} onCancel={onClose} className="method-dialog"><button className="dialog-close" onClick={onClose} autoFocus>Close</button><span className="eyebrow">PURPOSE, METHOD AND LIMITS</span><h2>Understanding planning constraints</h2>
    <p>This exploratory prototype asks whether trying a plan, examining solver feedback and changing rules can help people understand interacting planning constraints. No participant study has yet established a learning benefit. The app records no participant responses or analytics.</p>
    <h3>What does Z3 do?</h3>
    <p>A <strong>constraint</strong> is a rule that must be true. A <strong>constraint solver</strong> searches for choices that satisfy all your rules together. Z3 is the solver used in this tour; it is not a map service or a parcel forecast.</p>
    <p><a href="https://developers.google.com/optimization/cp" target="_blank" rel="noreferrer">Start with the concept: an introduction to constraint solving</a> (Google OR-Tools; the general idea, not the solver used here). <a href="https://www.microsoft.com/en-us/research/project/z3-3/" target="_blank" rel="noreferrer">About Z3 at Microsoft Research</a>.</p>
    <div className="method-step"><MapPin /><div><h3>1. Geography defines allowed connections.</h3><p>JavaScript calculates shortest directed walks from cell representative points, including their connectors to the paths. Only cell–locker pairs within 500 m are allowed. The illustrative drone rule uses twice the straight-line projected distance.</p></div></div>
    <div className="method-step"><Box /><div><h3>2. The model describes the choices.</h3><p>Open this locker? Assign this cell to it? Supply it from this depot on a normal day—or after each outage? Each is a yes/no variable. Counts and parcel totals must respect the limits.</p></div></div>
    <div className="method-step"><Cpu /><div><h3>3. Z3 checks the combination.</h3><p><code>SAT</code> means an assignment exists. <code>UNSAT</code> means none exists within this model. A timeout, cancellation or error is neither.</p></div></div>
    <div className="method-step"><CheckCircle2 /><div><h3>4. Separate code checks feasible answers.</h3><p>It reconstructs every chosen walking route, recomputes flight distances and counts every parcel in normal operation and in every depot-outage plan. These checks concern the encoded model; they do not independently validate the source data or planning assumptions.</p></div></div>
    <h3>Why use a solver here?</h3><p>A coverage map can show who could reach a locker. It cannot by itself choose capacity-feasible assignments for normal operation and every depot outage. Locker choice changes both collection and supply possibilities. Z3 handles their interaction in one model. This is not a claim that Z3 is the only tool: integer programming or custom search can model this problem too.</p>
    <details className="research-context"><summary>Research context and the next study</summary><p>The underlying methods belong to established research in constraint solving and facility location. The question for this prototype is whether its interface and explanations help people understand them.</p><ul><li><a href="https://www.microsoft.com/en-us/research/publication/z3-an-efficient-smt-solver/" target="_blank" rel="noreferrer">de Moura &amp; Bjørner (2008): Z3</a> — the solver's logical and arithmetic foundations.</li><li><a href="https://doi.org/10.1080/00207543.2017.1395490" target="_blank" rel="noreferrer">Deutsch &amp; Golany (2018): parcel locker network design</a> — a related facility-location model using integer programming.</li><li><a href="https://doi.org/10.1016/j.apgeog.2013.11.004" target="_blank" rel="noreferrer">Brown &amp; Kyttä (2014): public participation GIS</a> — research priorities including evaluation of planning-support effectiveness; not a study of this game.</li></ul><p>A proposed next study would compare a map-and-explanation version with the game plus solver feedback, then test understanding on an unfamiliar case. That study has not been conducted.</p></details>
    <h3>What this demonstration leaves out</h3><p>Candidate locations, demand (one parcel per ten residents, rounded up per cell), capacities and drone range are invented for teaching. One representative point stands for each 250 m population cell; the straight connector to its snapped path is included in the 500 m limit. This does not prove that every home is within 500 m.</p><p>The frozen map can be incomplete. Cell demand cannot be split. Flights ignore buildings, airspace, weather, take-off, battery reserves and schedules. The result is feasible, not optimal, and not an operational plan.</p>
    <CandidateExplanation scenario={scenario} />
    <p className="quiet">Snapshot: <code>{scenario.snapshotId}</code>. Walking graph: OpenStreetMap, August 2026; population: HSY 2025 edition. Source archives, licences and reproducible build instructions are included in the repository.</p>
    <p><a href="https://github.com/Z3Prover/z3" target="_blank" rel="noreferrer">Z3 project</a> · <a href="https://microsoft.github.io/z3guide/" target="_blank" rel="noreferrer">Z3 guide</a> · <a href={`${import.meta.env.BASE_URL}data/scenario.json`} download>Download this geographic snapshot</a> · <a href={`${import.meta.env.BASE_URL}third-party-notices.txt`} target="_blank" rel="noreferrer">Software notices</a></p>
  </dialog>
}
