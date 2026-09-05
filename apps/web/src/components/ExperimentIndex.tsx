import type { MouseEvent } from 'react'
import {
  ArrowDown,
  ArrowRight,
  Braces,
  GitBranch,
  Layers3,
  Network,
  ShieldCheck,
  Sprout,
  UsersRound,
  Waves,
} from 'lucide-react'
import './ExperimentIndex.css'

interface ExperimentIndexProps {
  onOpenModalFilters: () => void
  onOpenResilientAccess: () => void
  onOpenServiceCoverage: () => void
  onOpenSolverGuide: () => void
}

export function ExperimentIndex({
  onOpenModalFilters,
  onOpenResilientAccess,
  onOpenServiceCoverage,
  onOpenSolverGuide,
}: ExperimentIndexProps) {
  return (
    <main className="experiment-index" aria-labelledby="experiment-index-title">
      <div className="experiment-index__inner">
        <section className="experiment-index__hero">
          <div>
            <span className="experiment-index__eyebrow">Constraint solving × geographic networks</span>
            <h1 id="experiment-index-title" data-page-heading tabIndex={-1}>Spatial questions become choices, rules and checked routes.</h1>
          </div>
          <div className="experiment-index__introduction">
            <p>GIS describes the place. A network solver tests what connects. Z3 searches combinations of interventions or commitments that can satisfy several rules at once.</p>
            <p>Each experiment keeps those jobs separate and inspectable: GIS compiles the geographic relationships; Z3 chooses; an independent checker verifies the result.</p>
            <div className="experiment-index__hero-actions">
              <button type="button" onClick={onOpenSolverGuide}><Network size={16} /> How the solvers work</button>
              <a href="#lab-concepts"><ArrowDown size={15} /> Key concepts</a>
            </div>
          </div>
        </section>

        <section className="experiment-index__method" aria-labelledby="shared-method-title">
          <header>
            <span>Shared research pattern</span>
            <h2 id="shared-method-title">One proof boundary, different model shapes</h2>
          </header>
          <ol>
            <li><span>01</span><Layers3 size={17} /><strong>Compile evidence</strong><p>Freeze spatial data and state the graph assumptions explicitly.</p></li>
            <li><span>02</span><Braces size={17} /><strong>Choose variables</strong><p>Define the limited interventions, commitments and hard rules.</p></li>
            <li><span>03</span><GitBranch size={17} /><strong>Compile or refine</strong><p>Encode a complete finite relation, or teach Z3 with geographic counterexamples.</p></li>
            <li><span>04</span><ShieldCheck size={17} /><strong>Verify afresh</strong><p>Rebuild the final network and check every required connection again.</p></li>
          </ol>
        </section>

        <section className="experiment-index__experiments" aria-labelledby="experiments-title">
          <header>
            <div>
              <span className="experiment-index__eyebrow">Frozen, reproducible studies</span>
              <h2 id="experiments-title">Choose an experiment</h2>
            </div>
            <p>No study is a forecast, suitability assessment or operational plan. Each proves a narrower statement under its current data and model assumptions.</p>
          </header>

          <div className="experiment-grid">
            <article className="experiment-card experiment-card--coverage">
              <ExperimentPreview kind="coverage" />
              <div className="experiment-card__body">
                <div className="experiment-card__identity">
                  <span>Experiment 03 · Otaniemi–Tapiola, Espoo</span>
                  <h3>Equitable service coverage</h3>
                  <p>Capacitated public-facility selection and demand assignment</p>
                </div>
                <blockquote>Which reviewed sites can serve every included population cell within the stated walking distance and analytical capacity?</blockquote>
                <dl>
                  <div><dt>Spatial evidence</dt><dd>Official population grid and public facilities plus an OSM walking network</dd></div>
                  <div><dt>Solver choices</dt><dd>Open-site and exact cell-to-site assignment Booleans</dd></div>
                  <div><dt>Checked output</dt><dd>Walking distance, eligibility, budget and declared-capacity compliance</dd></div>
                </dl>
                <a href="?experience=coverage" onClick={(event) => openExperiment(event, onOpenServiceCoverage)}>
                  <UsersRound size={17} /><span><strong>Open service coverage</strong><small>Explore the allocation model</small></span><ArrowRight size={17} />
                </a>
              </div>
            </article>

            <article className="experiment-card experiment-card--resilience">
              <ExperimentPreview kind="resilience" />
              <div className="experiment-card__body">
                <div className="experiment-card__identity">
                  <span>Experiment 02 · Otaniemi, Espoo</span>
                  <h3>Resilient access</h3>
                  <p>Coastal flood exposure, roadworks and continuity choices</p>
                </div>
                <blockquote>Can representative address areas retain a path to a permitted network exit when explicit disruption assumptions remove road links?</blockquote>
                <dl>
                  <div><dt>Spatial evidence</dt><dd>OSM network, SYKE exposure and City of Espoo address/building data</dd></div>
                  <div><dt>Solver choices</dt><dd>Grouped continuity commitments within a selected budget</dd></div>
                  <div><dt>Checked output</dt><dd>Address-to-exit reachability, dependencies and mapped detour</dd></div>
                </dl>
                <a href="?experience=resilience" onClick={(event) => openExperiment(event, onOpenResilientAccess)}>
                  <Waves size={17} /><span><strong>Open resilient access</strong><small>Explore the Otaniemi stress test</small></span><ArrowRight size={17} />
                </a>
              </div>
            </article>

            <article className="experiment-card experiment-card--filters">
              <ExperimentPreview kind="filters" />
              <div className="experiment-card__body">
                <div className="experiment-card__identity">
                  <span>Experiment 01 · Kallio–Vallila, Helsinki</span>
                  <h3>Four Planters</h3>
                  <p>Modal-filter placement and neighbourhood permeability</p>
                </div>
                <blockquote>Can a small number of mode-specific street filters cut selected private-car through-routes while every address cluster retains access?</blockquote>
                <dl>
                  <div><dt>Spatial evidence</dt><dd>OSM directed streets, buildings, portals and protected corridors</dd></div>
                  <div><dt>Solver choices</dt><dd>Eligible street-edge filters, with force and lock-open constraints</dd></div>
                  <div><dt>Checked output</dt><dd>Portal-pair disconnection plus retained local private-car access</dd></div>
                </dl>
                <a href="?experience=baseline" onClick={(event) => openExperiment(event, onOpenModalFilters)}>
                  <Sprout size={17} /><span><strong>Open Four Planters</strong><small>Explore modal-filter placement</small></span><ArrowRight size={17} />
                </a>
              </div>
            </article>

          </div>
        </section>

        <section className="experiment-index__concepts" id="lab-concepts" aria-labelledby="concepts-title">
          <header>
            <span className="experiment-index__eyebrow">Working vocabulary</span>
            <h2 id="concepts-title">What the model’s terms mean</h2>
            <p>These are analytical concepts with deliberately narrow meanings. Reading them literally prevents a solver result from being mistaken for a field or policy conclusion.</p>
          </header>

          <article className="concept-feature">
            <div className="concept-feature__term"><span>Core concept</span><h3>Continuity commitment</h3><code>passable[zone] ∈ {'{false, true}'}</code></div>
            <div className="concept-feature__definition">
              <p>A continuity commitment is one <strong>Boolean choice in the resilient-access model</strong>. It asks whether a defined group of road fragments may be restored to the analytical graph after the chosen flood-exposure rule removed them.</p>
              <div className="concept-feature__example" aria-label="Continuity commitment example">
                <span><b>1</b> commitment</span><ArrowRight size={16} /><span><b>1</b> map-visible zone</span><ArrowRight size={16} /><span><b>several</b> OSM fragments</span>
              </div>
              <dl className="concept-feature__anatomy">
                <div><dt>How the group is built</dt><dd>Connected flood-exposed OSM fragments with the same normalized street name are grouped together. Unnamed fragments use mapped way and road-class continuity. A group is a solver decision unit, not necessarily one physical project.</dd></div>
                <div><dt>What true means</dt><dd><code>passable[zone] = true</code> returns those fragments only when the encoded flood assumption removed them. User-declared roadworks are fixed closures: they are excluded from the group and Z3 cannot reopen them.</dd></div>
                <div><dt>How Z3 learns it may be needed</dt><dd>If an origin is stranded, the graph checker finds its directed reachable-set frontier. A learned clause requires at least one eligible continuity group crossing that frontier; Z3 chooses a combination that works across all origins.</dd></div>
                <div><dt>How it is counted</dt><dd>The budget counts the group once when selected. The result also reports its expanded street-fragment count, so one convenient Boolean cannot masquerade as one simple field action.</dd></div>
              </dl>
              <p className="concept-caution"><strong>It is a model dependency—not a promise or finding in the field.</strong> Selection means the group belongs to the returned optimal assignment under the current objectives; it may not be indispensable in every equally good alternative. It does not establish that a road is dry, safe, legally open, funded, maintained or physically operable.</p>
            </div>
          </article>

          <div className="concept-grid">
            <Concept
              term="Scenario assumption"
              definition="An explicit rule that converts evidence into a graph state—for example, treating every road link with horizontal 1/1,000 flood overlap as unavailable. The source layer alone does not make that passability claim."
            />
            <Concept
              term="Decision variable and decision group"
              definition="A decision variable is a value Z3 may choose, often true or false. A decision group deliberately makes several mapped features share one value. The grouping makes the search legible and fast, but its granularity is itself an assumption to inspect."
            />
            <Concept
              term="Modal filter"
              definition="A mode-specific restriction attached to an eligible street edge. In the Kallio experiment it blocks private cars while walking, cycling and emergency access follow separately stated assumptions. A planter is only one possible physical treatment."
            />
            <Concept
              term="Counterexample"
              definition="A concrete route or stranded origin showing that Z3’s current proposal does not yet satisfy the geographic requirement. It is evidence for refinement, not a failed final answer."
            />
            <Concept
              term="Learned route or frontier clause"
              definition="A necessary logical rule extracted from a graph counterexample. A surviving through-route requires at least one eligible filter on that route; a stranded origin requires at least one eligible continuity group across its directed frontier. The map explains the failure and the clause refines Z3."
            />
            <Concept
              term="Hard constraint and objective"
              definition="A hard constraint must hold: budgets, forced or forbidden choices, route cuts and retained access. An objective ranks assignments that already satisfy every hard rule. Lexicographic objectives keep priorities explicit instead of hiding them in one blended score."
            />
            <Concept
              term="Portal pair and gateway"
              definition="A portal pair names two neighbourhood boundary crossings that must not remain connected in the modal-filter study. A gateway is a permitted outside-network destination that an origin may reach in the resilient-access study. Neither is a traffic count or certified safe destination."
            />
            <Concept
              term="Fresh verification"
              definition="A feasible final assignment is applied to a newly rebuilt NetworkX graph and its requested connectivity is checked again outside Z3. This guards the proof boundary between the compact logical model and the full directed street network; it does not replay an impossibility proof."
            />
            <Concept
              term="Verified, UNSAT and indeterminate"
              definition="Verified feasible means the fresh connectivity check passed under the encoded assumptions. Verified UNSAT follows when Z3 proves the active hard constraints and sound graph-derived clauses inconsistent, or when the graph exposes a required cut with no eligible decision. An UNSAT core may identify conflicting tracked assumptions. Timeout or cancellation is indeterminate and proves neither feasibility nor impossibility."
            />
            <Concept
              term="Demand cell"
              definition="One aggregate population-grid unit included in the allocation model. Its resident count is an analytical demand weight assigned as a whole to one site; it is not individual, address-level or observed service-use data."
            />
            <Concept
              term="Assignment pair"
              definition="A Boolean relationship between one demand cell and one candidate site, admitted only when the frozen walking graph contains a route within the active distance limit. Exactly one pair must be true for every included cell."
            />
            <Concept
              term="Analytical capacity"
              definition="A declared scenario limit on the population weight assigned to a selected site. It supports sensitivity testing but does not describe rooms, staff, opening hours, queues, accessibility or actual service throughput."
            />
          </div>
        </section>

        <footer className="experiment-index__footer">
          <span>Geospatial Constraint Lab</span>
          <p>Frozen evidence · explicit assumptions · inspectable choices · independent graph verification</p>
        </footer>
      </div>
    </main>
  )
}

function openExperiment(event: MouseEvent<HTMLAnchorElement>, onOpen: () => void) {
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
  event.preventDefault()
  onOpen()
}

function Concept({ term, definition }: { term: string; definition: string }) {
  return <article><h3>{term}</h3><p>{definition}</p></article>
}

function ExperimentPreview({ kind }: { kind: 'filters' | 'resilience' | 'coverage' }) {
  if (kind === 'filters') {
    return (
      <figure className="experiment-preview" aria-label="Schematic modal-filter network">
        <div className="experiment-preview__label" aria-hidden="true"><span>Experiment 01 · Kallio</span><strong>Four Planters</strong></div>
        <svg viewBox="0 0 620 215" aria-hidden="true">
          <path className="preview-boundary" d="M78 32 L520 26 L574 107 L521 187 L91 178 L43 102 Z" />
          <g className="preview-roads">
            <path d="M20 105 L151 99 L265 103 L383 101 L600 106" />
            <path d="M305 3 L301 65 L306 104 L310 211" />
            <path d="M72 38 L151 99 L126 175 M220 30 L265 103 L204 179 M406 28 L383 101 L434 186 M530 52 L489 104 L535 174" />
            <path d="M151 99 L220 30 M265 103 L406 28 M383 101 L535 174" />
          </g>
          <g className="preview-filters"><path d="M143 86 L158 112" /><path d="M291 146 L325 146" /><path d="M398 89 L393 115" /><path d="M475 91 L494 116" /></g>
          <g className="preview-portals"><circle cx="20" cy="105" r="8" /><circle cx="305" cy="3" r="8" /><circle cx="600" cy="106" r="8" /><circle cx="310" cy="211" r="8" /></g>
        </svg>
        <figcaption><span>4 selected filters</span><strong>portal routes cut · local access checked</strong></figcaption>
      </figure>
    )
  }
  if (kind === 'resilience') return (
    <figure className="experiment-preview" aria-label="Schematic coastal access network">
      <div className="experiment-preview__label" aria-hidden="true"><span>Experiment 02 · Otaniemi</span><strong>Resilient access</strong></div>
      <svg viewBox="0 0 620 215" aria-hidden="true">
        <path className="preview-coast" d="M0 0 H620 V67 C560 51 528 77 497 104 C457 140 401 136 357 168 C306 205 229 172 176 198 C119 225 54 201 0 184 Z" />
        <g className="preview-roads">
          <path d="M23 178 L121 140 L221 149 L327 120 L417 97 L596 74" />
          <path d="M93 29 L121 140 L172 201 M194 19 L221 149 L290 205 M350 15 L327 120 L383 188 M503 16 L417 97 L502 145" />
          <path d="M93 29 L194 19 L350 15 L503 16 M121 140 L194 19 M221 149 L350 15 M327 120 L502 145" />
        </g>
        <g className="preview-unavailable"><path d="M23 178 L121 140" /><path d="M221 149 L327 120" /><path d="M417 97 L502 145" /></g>
        <path className="preview-route" d="M172 201 L121 140 L221 149 L194 19 L350 15 L503 16" />
        <g className="preview-commitments"><circle cx="121" cy="140" r="13" /><circle cx="221" cy="149" r="13" /><circle cx="417" cy="97" r="13" /></g>
        <g className="preview-origins"><circle cx="172" cy="201" r="8" /><rect x="494" y="7" width="18" height="18" transform="rotate(45 503 16)" /></g>
      </svg>
      <figcaption><span>3 continuity commitments</span><strong>21 links · access verified</strong></figcaption>
    </figure>
  )
  return (
    <figure className="experiment-preview" aria-label="Schematic population-to-service assignment">
      <div className="experiment-preview__label" aria-hidden="true"><span>Experiment 03 · Otaniemi–Tapiola</span><strong>Service coverage</strong></div>
      <svg viewBox="0 0 620 215" aria-hidden="true">
        <g className="preview-population-grid">
          <rect x="35" y="28" width="83" height="68" /><rect x="122" y="28" width="83" height="68" /><rect x="209" y="28" width="83" height="68" /><rect x="296" y="28" width="83" height="68" /><rect x="383" y="28" width="83" height="68" /><rect x="470" y="28" width="83" height="68" />
          <rect x="35" y="100" width="83" height="68" /><rect x="122" y="100" width="83" height="68" /><rect x="209" y="100" width="83" height="68" /><rect x="296" y="100" width="83" height="68" /><rect x="383" y="100" width="83" height="68" /><rect x="470" y="100" width="83" height="68" />
        </g>
        <g className="preview-assignment-routes">
          <path d="M77 62 L164 132 L250 62" /><path d="M338 62 L424 132 L511 62" /><path d="M77 134 L164 132 L250 134" /><path d="M338 134 L424 132 L511 134" />
        </g>
        <g className="preview-service-sites"><circle cx="164" cy="132" r="17" /><circle cx="424" cy="132" r="17" /></g>
        <g className="preview-demand-dots"><circle cx="77" cy="62" r="5" /><circle cx="164" cy="62" r="7" /><circle cx="250" cy="62" r="6" /><circle cx="338" cy="62" r="5" /><circle cx="424" cy="62" r="8" /><circle cx="511" cy="62" r="6" /><circle cx="77" cy="134" r="6" /><circle cx="250" cy="134" r="5" /><circle cx="338" cy="134" r="7" /><circle cx="511" cy="134" r="5" /></g>
      </svg>
      <figcaption><span>capacitated assignment</span><strong>walking routes · every cell checked</strong></figcaption>
    </figure>
  )
}
