import type { Scenario } from '../core/types.ts'

export function CandidateExplanation({ scenario }: { scenario: Scenario }) {
  return <details className="candidate-explanation">
    <summary>Where did the candidate sites come from?</summary>
    <p><strong>The {scenario.lockers.length} locker candidates A–X are invented for this lesson.</strong> They are points on real mapped walking paths, not existing parcel lockers or approved building sites.</p>
    <ol>
      <li>Start with mapped walking points that a population cell can reach within <strong>500 m</strong>, including its connector to the path.</li>
      <li>Add the point that gives the most cells another option, prioritising cells that still have fewer than three. Keep candidate sites at least <strong>80 m apart</strong>.</li>
      <li>Stop once every cell has at least <strong>three possible collection sites</strong>. Here that produces {scenario.lockers.length} candidates.</li>
    </ol>
    <p>This simple shortlist rule considers walking only—not locker capacity or drone supply. <strong>Z3's job comes later:</strong> choose which candidates to open and how to connect them, while satisfying all the rules together. Each cell ultimately uses just one locker.</p>
    <p className="quiet">Ties favour the shortest worst useful walk, then the map node ID. The 80 m spacing is only a shortlist-design choice; the resident walking limit is still 500 m. Four depot candidates sit around the demand area; two more are the nearest mapped nodes to reproducible central-east and central-west target points. None has been checked for buildability.</p>
    <p className="quiet">In step 1, the eight teal lockers form a prepared collection example only so walking routes can be inspected. They are not the game’s starting layout or a claim that these are the best sites.</p>
  </details>
}
