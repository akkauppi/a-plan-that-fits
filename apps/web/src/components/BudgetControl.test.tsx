import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { BudgetControl } from './BudgetControl'

describe('BudgetControl', () => {
  it('announces the default budget and allows keyboard-friendly increments', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    render(<BudgetControl value={4} onChange={onChange} />)

    expect(screen.getByLabelText('4 interventions')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Increase intervention budget' }))
    expect(onChange).toHaveBeenCalledWith(5)
  })

  it('cannot decrement below zero', () => {
    render(<BudgetControl value={0} onChange={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Decrease intervention budget' })).toBeDisabled()
  })
})
