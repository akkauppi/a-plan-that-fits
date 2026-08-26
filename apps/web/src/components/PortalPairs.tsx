import { useState } from 'react'
import { ArrowLeftRight, ChevronDown, SlidersHorizontal } from 'lucide-react'
import type { Portal, PortalPair } from '../types'
import { pairKey } from '../types'

interface PortalPairsProps {
  pairs: PortalPair[]
  portals: Portal[]
  selectedKeys: string[]
  onChange: (keys: string[]) => void
  disabled?: boolean
}

export function PortalPairs({ pairs, portals, selectedKeys, onChange, disabled = false }: PortalPairsProps) {
  const [showAll, setShowAll] = useState(false)
  const numberFor = (id: string) => portals.findIndex((portal) => portal.id === id) + 1
  const visiblePairs = showAll
    ? pairs
    : pairs.filter((pair, index) => selectedKeys.includes(pairKey(pair)) || index < 2)
  const toggle = (pair: PortalPair) => {
    const key = pairKey(pair)
    onChange(selectedKeys.includes(key) ? selectedKeys.filter((item) => item !== key) : [...selectedKeys, key])
  }
  return (
    <details className="disclosure" open>
      <summary>
        <span className="summary-icon"><ArrowLeftRight size={15} aria-hidden="true" /></span>
        <span><strong>Routes to disconnect</strong><small>{selectedKeys.length} portal {selectedKeys.length === 1 ? 'pair' : 'pairs'} required</small></span>
        <ChevronDown className="disclosure__chevron" size={16} aria-hidden="true" />
      </summary>
      <div className="portal-pairs">
        {visiblePairs.map((pair) => {
          const key = pairKey(pair)
          const checked = selectedKeys.includes(key)
          return (
            <label key={key} className={`portal-pair ${checked ? 'is-checked' : ''}`}>
              <input type="checkbox" checked={checked} onChange={() => toggle(pair)} disabled={disabled} />
              <span className="portal-pair__route" aria-hidden="true">
                <b>{numberFor(pair.a)}</b><i /><b>{numberFor(pair.b)}</b>
              </span>
              <span><strong>{pair.label}</strong><small>no private-car connection</small></span>
            </label>
          )
        })}
        {!pairs.length && <p className="quiet-copy">This scenario does not define portal-pair requirements.</p>}
        {pairs.length > visiblePairs.length && (
          <button type="button" className="show-pairs-button" onClick={() => setShowAll(true)} disabled={disabled}>
            <SlidersHorizontal size={13} /> Choose other portal pairs <span>{pairs.length - visiblePairs.length}</span>
          </button>
        )}
        {showAll && pairs.length > 2 && (
          <button type="button" className="show-pairs-button" onClick={() => setShowAll(false)} disabled={disabled}>Show selected pairs only</button>
        )}
      </div>
      <p className="field-note">This is a network-permeability condition, not a prediction of traffic volumes.</p>
    </details>
  )
}
