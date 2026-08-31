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

export function SolverComparisonPage({ onClose }: { onClose: () => void }) {
  return (
    <main className="solver-guide" aria-labelledby="solver-guide-title">
      <div className="solver-guide__inner">
        <button type="button" className="solver-guide__back" onClick={onClose}>
          <ArrowLeft size={15} /> Return to the live map
        </button>

        <header className="solver-guide__hero">
          <div>
            <span className="solver-guide__eyebrow">A five-minute solver guide</span>
            <h1 id="solver-guide-title">A route finder searches a network.<br />Z3 searches combinations of choices.</h1>
          </div>
          <p>They answer different questions. Four Planters uses both because choosing a network intervention and checking its geographic effect are different jobs.</p>
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
          <p><span>One sentence for the meeting</span><strong>Routing tells us whether a proposed network works. Z3 helps decide which proposal to test next.</strong></p>
        </aside>

        <section className="solver-guide__loop" aria-labelledby="solver-loop-title">
          <header>
            <span className="solver-guide__eyebrow">The Four Planters method</span>
            <h2 id="solver-loop-title">The graph checker teaches the compact model</h2>
            <p>Z3 never has to contain every possible street path. Instead, it proposes a small decision set and receives a precise counterexample whenever the real directed graph disagrees.</p>
          </header>
          <ol>
            <li><span>01</span><Map size={18} /><strong>Compile map facts</strong><p>Frozen links, explicit unavailable-link assumptions, origins and permitted exits.</p></li>
            <li><span>02</span><Braces size={18} /><strong>Z3 proposes</strong><p>A set of continuity-zone Booleans within the selected budget.</p></li>
            <li><span>03</span><Route size={18} /><strong>NetworkX checks</strong><p>Apply that assignment to the full directed graph and route every selected origin.</p></li>
            <li className="solver-guide__loop-counterexample"><span>04</span><GitBranch size={18} /><strong>Return a counterexample</strong><p>A stranded origin yields its reachable region and eligible outgoing frontier.</p></li>
            <li><span>05</span><ShieldCheck size={18} /><strong>Rebuild and verify</strong><p>Repeat until a fresh graph passes—or the encoded choices are proved insufficient.</p></li>
          </ol>
          <div className="solver-guide__clause">
            <span>One learned rule</span>
            <code>passable[zone_a] ∨ passable[zone_b]</code>
            <p>Plain language: at least one eligible continuity zone on this directed frontier must be available. The diagnostic route explains the failure; the frontier is the sound constraint.</p>
          </div>
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
          <div><span>Four Planters · solver guide</span><p>NetworkX supplies geographic witnesses. Z3 manages combinations and logic. Fresh graph reconstruction checks the final assignment.</p></div>
          <button type="button" onClick={onClose}>Return to the experiment <ArrowRight size={15} /></button>
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
        <span><b>Budget</b> choose at most 4 zones</span>
        <span><b>Access</b> every origin reaches any permitted exit</span>
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
