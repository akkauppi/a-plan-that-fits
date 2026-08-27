import type { SolveResult, SolveStatus } from './types'

export function statusFromResult(result: SolveResult): SolveStatus {
  const status = String(result.status ?? '').toLowerCase().replace(/\s+/g, '_')
  const verification = String(result.verification_status ?? '').toLowerCase().replace(/\s+/g, '_')
  if ((status === 'verified_sat' || status === 'verified_optimal') && verification === 'independently_verified') {
    return status
  }
  if (
    status === 'verified_unsat' &&
    ['z3_unsat_core', 'graph_unblockable_route', 'independently_verified'].includes(verification)
  ) {
    return 'verified_unsat'
  }
  if (status === 'timeout' || status === 'cancelled' || status === 'data_error') return status
  return 'data_error'
}
