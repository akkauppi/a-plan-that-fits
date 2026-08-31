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
    expect(screen.getByText(/routing tells us whether a proposed network works/i)).toBeInTheDocument()
    expect(screen.getByText(/verified model answer is not a forecast/i)).toBeInTheDocument()
  })

  it('returns to the experiment', async () => {
    const onClose = vi.fn()
    render(<SolverComparisonPage onClose={onClose} />)
    await userEvent.click(screen.getByRole('button', { name: /return to the live map/i }))
    expect(onClose).toHaveBeenCalledOnce()
  })
})
