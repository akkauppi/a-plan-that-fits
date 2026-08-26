import { Minus, Plus } from 'lucide-react'

interface BudgetControlProps {
  value: number
  onChange: (value: number) => void
  disabled?: boolean
}

export function BudgetControl({ value, onChange, disabled = false }: BudgetControlProps) {
  const set = (next: number) => onChange(Math.min(8, Math.max(0, next)))
  return (
    <div className="budget-control">
      <div className="budget-control__label">
        <span>Intervention budget</span>
        <span className="budget-control__hint">maximum</span>
      </div>
      <div className="budget-control__input">
        <button type="button" onClick={() => set(value - 1)} disabled={disabled || value <= 0} aria-label="Decrease intervention budget">
          <Minus size={18} aria-hidden="true" />
        </button>
        <output aria-live="polite" aria-label={`${value} interventions`}>
          <strong>{value}</strong>
          <span>{value === 1 ? 'filter' : 'filters'}</span>
        </output>
        <button type="button" onClick={() => set(value + 1)} disabled={disabled || value >= 8} aria-label="Increase intervention budget">
          <Plus size={18} aria-hidden="true" />
        </button>
      </div>
      <input
        className="budget-range"
        type="range"
        min="0"
        max="8"
        step="1"
        value={value}
        style={{ background: `linear-gradient(to right, var(--orange) 0%, var(--orange) ${value * 12.5}%, #cfcbc1 ${value * 12.5}%, #cfcbc1 100%)` }}
        onChange={(event) => set(Number(event.target.value))}
        disabled={disabled}
        aria-label="Intervention budget"
      />
      <div className="budget-range__ticks" aria-hidden="true"><span>0</span><span>4</span><span>8</span></div>
    </div>
  )
}
