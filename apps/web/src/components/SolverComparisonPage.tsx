import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Braces,
  Check,
  GitBranch,
  Map,
  Network,
  Route,
  ShieldCheck,
  SlidersHorizontal,
} from 'lucide-react'
import './SolverComparisonPage.css'

export function SolverComparisonPage({
  onClose,
  returnLabel = 'Return to the experiment',
}: {
  onClose: () => void
  returnLabel?: string
}) {
  return (
    <main className="solver-guide" aria-labelledby="solver-guide-title">
      <div className="solver-guide__inner">
        <button type="button" className="solver-guide__back" onClick={onClose}>
          <ArrowLeft size={15} /> {returnLabel}
        </button>

        <header className="solver-guide__hero">
          <div>
            <span className="solver-guide__eyebrow">A five-minute solver guide</span>
            <h1 id="solver-guide-title" data-page-heading tabIndex={-1}>A route finder searches a network.<br />Z3 searches combinations of choices.</h1>
          </div>
          <p>They answer different questions. The experiments use both because choosing a spatial intervention and checking its geographic effect are different jobs.</p>
        </header>

        <section className="solver-guide__comparison" aria-label="Solver comparison">
          <article className="solver-role solver-role--network">
            <header>
              <span><Route size={19} /></span>
              <div><small>Typical navigation / network solver</small><h2>“Does a route exist in this fixed network?”</h2></div>
            </header>
            <NetworkSketch />
            <dl>
              <div><dt>Given</dt><dd>Nodes, directed links, lengths and a known open/closed state</dd></div>
              <div><dt>Good at</dt><dd>Shortest paths, reachability, service areas, components and cut frontiers</dd></div>
              <div><dt>Returns</dt><dd>A route, a reachable region, or a concrete witness that no route remains</dd></div>
            </dl>
          </article>

          <div className="solver-guide__not-versus" aria-hidden="true">
            <span>not versus</span><strong>+</strong><span>working together</span>
          </div>

          <article className="solver-role solver-role--z3">
            <header>
              <span><Braces size={19} /></span>
              <div><small>Z3 constraint solver</small><h2>“Which combination of choices can satisfy all the rules?”</h2></div>
            </header>
            <ConstraintSketch />
            <dl>
              <div><dt>Given</dt><dd>Decision variables, a budget, requirements, exclusions and priorities</dd></div>
              <div><dt>Good at</dt><dd>Boolean choices, logical dependencies, competing requirements and schedules</dd></div>
              <div><dt>Returns</dt><dd>A satisfying assignment—or UNSAT when no encoded assignment can work</dd></div>
            </dl>
          </article>
        </section>

        <aside className="solver-guide__meeting-line">
          <Network size={20} />
          <p><span>One sentence for the meeting</span><strong>Network analysis supplies geographic relationships and checks. Z3 chooses a combination that obeys all the rules.</strong></p>
        </aside>

        <section className="solver-guide__loop" aria-labelledby="solver-loop-title">
          <header>
            <span className="solver-guide__eyebrow">Counterexample-guided pattern · experiments 01 and 02</span>
            <h2 id="solver-loop-title">When every possible route is too large to encode upfront</h2>
            <p>The modal-filter and resilient-access studies do not put every street path into Z3. The solver proposes a small decision set and receives a precise counterexample whenever the real directed graph disagrees.</p>
          </header>
          <ol>
            <li><span>01</span><Map size={18} /><strong>Compile map facts</strong><p>Freeze the directed graph, eligible decisions, protected links, origins, portals and availability assumptions.</p></li>
            <li><span>02</span><Braces size={18} /><strong>Z3 proposes</strong><p>Choose filter-edge or continuity-zone Booleans under the budget, locks and other hard rules.</p></li>
            <li><span>03</span><Route size={18} /><strong>NetworkX checks</strong><p>Look for a surviving forbidden through-route or an origin that cannot reach a permitted exit.</p></li>
            <li className="solver-guide__loop-counterexample"><span>04</span><GitBranch size={18} /><strong>Return a counterexample</strong><p>Translate that route or directed reachable-set frontier into a necessary clause over eligible choices.</p></li>
            <li><span>05</span><ShieldCheck size={18} /><strong>Rebuild and verify</strong><p>Freshly check every requested disconnection and retained-access requirement before making a claim.</p></li>
          </ol>
          <div className="solver-guide__clause">
            <span>Two learned-rule patterns</span>
            <div className="solver-guide__clause-rules">
              <span><code>blocked[edge_a] ∨ blocked[edge_b]</code><small>Modal filters: cut this surviving route.</small></span>
              <span><code>passable[zone_a] ∨ passable[zone_b]</code><small>Resilient access: cross this directed frontier.</small></span>
            </div>
            <p>Each clause says “at least one of these choices must change.” The mapped route explains the failure to a person; the eligible route edges or reachable-set frontier supply the sound logical rule.</p>
          </div>
        </section>

        <section className="solver-guide__allocation" aria-labelledby="allocation-model-title">
          <header>
            <span className="solver-guide__eyebrow">Compiled allocation pattern · experiment 03</span>
            <h2 id="allocation-model-title">When GIS can compile the complete choice table</h2>
            <p>Service coverage is different. NetworkX first calculates every reviewed demand-to-site walking distance. The resulting finite table is small enough for Z3 to receive the whole assignment question at once—no path-refinement loop is needed.</p>
          </header>
          <div className="solver-guide__allocation-flow" aria-label="Service allocation calculation sequence">
            <article>
              <span>01 · GIS / NetworkX</span>
              <strong>Compile walking pairs</strong>
              <code>assign[cell, site] ⇒ distance[cell, site] ≤ limit</code>
              <p>Each pair is backed by a frozen walking route in metres. The distance rule makes over-limit assignments unavailable rather than merely giving them a poor score.</p>
            </article>
            <ArrowRight aria-hidden="true" />
            <article>
              <span>02 · Z3</span>
              <strong>Choose sites and assignments</strong>
              <code>open[site] · assign[cell, site]</code>
              <p>Booleans are selected together under budget, exact assignment, distance, capacity, force and prohibition rules.</p>
            </article>
            <ArrowRight aria-hidden="true" />
            <article>
              <span>03 · fresh verifier</span>
              <strong>Repeat every check</strong>
              <code>route · load · budget · forced / prohibited sites</code>
              <p>The returned routes and site loads are recomputed outside the Z3 model before the assignment is called verified.</p>
            </article>
          </div>
          <div className="solver-guide__allocation-constraints">
            <div>
              <span>What goes into Z3</span>
              <code>Σ open[site] ≤ site_budget</code>
              <code>∀ cell: Σ assign[cell, site] = 1</code>
              <code>assign[cell, site] ⇒ open[site]</code>
              <code>Σ population[cell] × assign[cell, site] ≤ capacity[site]</code>
            </div>
            <p><strong>The map and the logical model show the same finite relationships.</strong> A population cell must be assigned exactly once; its assignment can use only an open, reachable site; and all assigned residents count against that site’s declared analytical capacity. Objectives then minimise site count, worst walking distance, total weighted distance and load imbalance—in that explicit order.</p>
          </div>
          <p className="solver-guide__allocation-note"><Check size={14} /> Counterexample-guided refinement is a useful technique, not a requirement of constraint solving. The model structure should follow the question and the tractable representation.</p>
        </section>

        <section className="solver-guide__walkthrough" aria-labelledby="walkthrough-title">
          <header>
            <span className="solver-guide__eyebrow">The actual Otaniemi teaching preset</span>
            <h2 id="walkthrough-title">A small trace you can narrate</h2>
            <p>The numbers below come from the frozen default experiment. “Unavailable” is an explicit stress-test rule applied to horizontal flood overlap—not an observed road closure.</p>
          </header>
          <div className="solver-guide__walkthrough-grid">
            <article><span>Start</span><strong>528</strong><p>private-car links are treated as unavailable under the selected 1/1,000 exposure rule.</p></article>
            <ArrowRight aria-hidden="true" />
            <article><span>First proposal</span><strong>0</strong><p>continuity commitments. The route checker reports that Otaranta is stranded.</p></article>
            <ArrowRight aria-hidden="true" />
            <article><span>Refine</span><strong>3</strong><p>successive graph frontiers become necessary clauses and strengthen Z3’s model.</p></article>
            <ArrowRight aria-hidden="true" />
            <article className="is-verified"><span>Checked answer</span><strong>3 zones</strong><p>expand to 21 links; a fresh graph retains access with a mapped +1,093 m detour.</p></article>
          </div>
          <p className="solver-guide__walkthrough-note"><Check size={14} /> Four is an upper bound, not a target. The solver stops at the minimum encoded dependency: three corridor zones in this scenario.</p>
        </section>

        <section className="solver-guide__questions" aria-labelledby="question-fit-title">
          <header>
            <span className="solver-guide__eyebrow">Choose the engine by the question</span>
            <h2 id="question-fit-title">What belongs where?</h2>
          </header>
          <div className="solver-guide__question-grid">
            <article>
              <Route size={18} /><h3>Use the network solver</h3>
              <p>When the network state is already known and the answer is a path, distance, reachable set, component or cut.</p>
              <ul><li>Fastest route to a clinic</li><li>Addresses inside a 15-minute service area</li><li>Links separating two components</li></ul>
            </article>
            <article>
              <SlidersHorizontal size={18} /><h3>Use Z3</h3>
              <p>When the answer is a combination of choices constrained by budgets, logic, incompatibilities or time.</p>
              <ul><li>Which works happen in which week</li><li>Which sites cover required services</li><li>Which choices must remain mutually compatible</li></ul>
            </article>
            <article className="is-combined">
              <Network size={18} /><h3>Use both</h3>
              <p>When every proposed combination changes a spatial network and must be checked against geographic consequences.</p>
              <ul><li>Resilient access under works and flooding</li><li>Evacuation or facility-continuity investments</li><li>Habitat links or utility-isolation plans</li></ul>
            </article>
          </div>
        </section>

        <section className="solver-guide__boundary" aria-labelledby="proof-boundary-title">
          <AlertTriangle size={20} />
          <div>
            <span className="solver-guide__eyebrow">Proof boundary</span>
            <h2 id="proof-boundary-title">A verified model answer is not a forecast or field approval</h2>
            <p>The computation can prove reachability or infeasibility only under its frozen graph, selected origins and exits, decision units, budget and availability assumptions. Neither engine proves that a road is physically safe, legally open, hydraulically passable, uncongested or operationally feasible.</p>
          </div>
        </section>

        <footer className="solver-guide__footer">
          <div><span>Geospatial Constraint Lab · solver guide</span><p>NetworkX supplies geographic witnesses. Z3 manages combinations and logic. Fresh graph reconstruction checks the final assignment.</p></div>
          <button type="button" onClick={onClose}>{returnLabel} <ArrowRight size={15} /></button>
        </footer>
      </div>
    </main>
  )
}

function NetworkSketch() {
  return (
    <figure className="solver-sketch solver-sketch--network">
      <svg viewBox="0 0 520 190" role="img" aria-labelledby="network-sketch-title network-sketch-description">
        <title id="network-sketch-title">A fixed street network with one highlighted route</title>
        <desc id="network-sketch-description">Grey links form a network. A teal route connects the origin to the destination around two unavailable red links.</desc>
        <g className="solver-sketch__roads">
          <path d="M40 145 L122 118 L208 142 L296 91 L382 110 L480 53" />
          <path d="M40 145 L104 62 L208 70 L296 91 L356 35 L480 53" />
          <path d="M122 118 L208 70 M208 142 L268 165 L382 110 M356 35 L382 110" />
        </g>
        <g className="solver-sketch__closed"><path d="M120 118 L205 142" /><path d="M296 91 L356 35" /></g>
        <path className="solver-sketch__route" d="M40 145 L104 62 L208 70 L296 91 L382 110 L480 53" />
        <g className="solver-sketch__nodes"><circle cx="40" cy="145" r="8" /><circle cx="104" cy="62" r="5" /><circle cx="122" cy="118" r="5" /><circle cx="208" cy="70" r="5" /><circle cx="208" cy="142" r="5" /><circle cx="296" cy="91" r="5" /><circle cx="268" cy="165" r="5" /><circle cx="356" cy="35" r="5" /><circle cx="382" cy="110" r="5" /><circle cx="480" cy="53" r="8" /></g>
        <text x="27" y="174">origin</text><text x="448" y="30">exit</text>
      </svg>
      <figcaption><span>one network state</span><strong>route / no route</strong></figcaption>
    </figure>
  )
}

function ConstraintSketch() {
  return (
    <figure className="solver-sketch solver-sketch--constraint">
      <div className="constraint-sketch__rules">
        <span><b>Budget</b> choose at most 4 decisions</span>
        <span><b>Rules</b> require selected connections or disconnections</span>
      </div>
      <div className="constraint-sketch__variables" aria-label="Example Boolean assignment">
        {[
          ['zone A', true],
          ['zone B', false],
          ['zone C', true],
          ['zone D', true],
          ['zone E', false],
          ['zone F', false],
        ].map(([label, selected]) => <span className={selected ? 'is-selected' : ''} key={String(label)}><i>{selected ? '1' : '0'}</i>{label}</span>)}
      </div>
      <figcaption><span>many possible assignments</span><strong>one combination that satisfies the rules</strong></figcaption>
    </figure>
  )
}
