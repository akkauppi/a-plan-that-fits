import type { SolveResult } from '../core/types.ts'

type Status = SolveResult['status']

export function comparisonConclusion(z3: Status, exhaustive: Status) {
  const conclusive = (status: Status) => status === 'feasible' || status === 'unsat'
  if (!conclusive(z3) || !conclusive(exhaustive)) {
    return { kind: 'inconclusive', message: 'At least one method returned no feasibility conclusion. A timeout, cancellation or error does not establish agreement or disagreement.' }
  }
  if (z3 !== exhaustive) {
    return { kind: 'disagrees', message: 'The methods disagree. Treat this as an implementation error, not a planning result.' }
  }
  return {
    kind: 'agrees',
    message: `Both methods reached the same ${z3 === 'feasible' ? 'feasible' : 'UNSAT'} conclusion. This supports implementation consistency; it does not validate the real-world assumptions.`,
  }
}
