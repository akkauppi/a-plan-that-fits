import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { SolverComparisonPage } from './SolverComparisonPage'

describe('SolverComparisonPage', () => {
  it('distinguishes fixed-network routing from constrained choice search', () => {
    render(<SolverComparisonPage onClose={() => undefined} />)
    expect(screen.getByRole('heading', { name: /route finder searches a network/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /does a route exist in this fixed network/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /which combination of choices/i })).toBeInTheDocument()
    expect(screen.getByText(/network analysis supplies geographic relationships/i)).toBeInTheDocument()
    expect(screen.getByText(/Modal filters: cut this surviving route/i)).toBeInTheDocument()
    expect(screen.getByText(/Resilient access: cross this directed frontier/i)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /GIS can compile the complete choice table/i })).toBeInTheDocument()
    expect(screen.getByText(/population cell must be assigned exactly once/i)).toBeInTheDocument()
    expect(screen.getByText(/verified model answer is not a forecast/i)).toBeInTheDocument()
    expect(screen.getByText(/Geospatial Constraint Lab · solver guide/i)).toBeInTheDocument()
  })

  it('returns to the experiment collection with the supplied label', async () => {
    const onClose = vi.fn()
    render(<SolverComparisonPage onClose={onClose} returnLabel="Return to all experiments" />)
    await userEvent.click(screen.getAllByRole('button', { name: /return to all experiments/i })[0]!)
    expect(onClose).toHaveBeenCalledOnce()
  })
})
