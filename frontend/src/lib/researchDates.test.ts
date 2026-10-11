import { describe, expect, it } from 'vitest'
import { researchDateOptions } from './researchDates'

describe('research date shortcuts', () => {
  it('keeps all synthetic API test presets inside the committed fixture', () => {
    const options = researchDateOptions('api', true, '2026-10-11')

    expect(options.initialWindow).toEqual({ start: '2025-12-01', end: '2025-12-31' })
    expect(options.presets).toEqual([
      { label: '1M', start: '2025-12-01', end: '2025-12-31' },
      { label: '3M', start: '2025-10-01', end: '2025-12-31' },
      { label: '1Y', start: '2025-01-01', end: '2025-12-31' },
    ])
  })

  it('keeps the current-date default for the ordinary API', () => {
    expect(researchDateOptions('api', false, '2026-10-11').initialWindow).toEqual({ start: '2026-10-01', end: '2026-10-11' })
  })
})
