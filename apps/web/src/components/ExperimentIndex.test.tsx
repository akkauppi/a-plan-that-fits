import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ExperimentIndex } from './ExperimentIndex'

describe('ExperimentIndex', () => {
  it('presents three studies as equal experiments and defines their core concepts', () => {
    render(
      <ExperimentIndex
        onOpenModalFilters={vi.fn()}
        onOpenResilientAccess={vi.fn()}
        onOpenServiceCoverage={vi.fn()}
        onOpenSolverGuide={vi.fn()}
      />,
    )

    expect(screen.getByRole('heading', { name: 'Four Planters' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Resilient access' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Equitable service coverage' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Continuity commitment' })).toBeInTheDocument()
    expect(screen.getByText(/budget counts the group once/i)).toBeInTheDocument()
    expect(screen.getByText(/Z3 cannot reopen them/i)).toBeInTheDocument()
    expect(screen.getByText(/not a promise or finding/i)).toBeInTheDocument()
    expect(screen.getByText(/feasible final assignment.*requested connectivity/i)).toBeInTheDocument()
    expect(screen.getByText(/Verified UNSAT follows when Z3 proves/i)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Analytical capacity' })).toBeInTheDocument()
  })

  it('opens either experiment and the shared method guide', async () => {
    const user = userEvent.setup()
    const onOpenModalFilters = vi.fn()
    const onOpenResilientAccess = vi.fn()
    const onOpenServiceCoverage = vi.fn()
    const onOpenSolverGuide = vi.fn()
    render(
      <ExperimentIndex
        onOpenModalFilters={onOpenModalFilters}
        onOpenResilientAccess={onOpenResilientAccess}
        onOpenServiceCoverage={onOpenServiceCoverage}
        onOpenSolverGuide={onOpenSolverGuide}
      />,
    )

    await user.click(screen.getByRole('link', { name: /Open Four Planters/i }))
    await user.click(screen.getByRole('link', { name: /Open resilient access/i }))
    await user.click(screen.getByRole('link', { name: /Open service coverage/i }))
    await user.click(screen.getByRole('button', { name: /How the solvers work/i }))

    expect(onOpenModalFilters).toHaveBeenCalledOnce()
    expect(onOpenResilientAccess).toHaveBeenCalledOnce()
    expect(onOpenServiceCoverage).toHaveBeenCalledOnce()
    expect(onOpenSolverGuide).toHaveBeenCalledOnce()
  })
})
