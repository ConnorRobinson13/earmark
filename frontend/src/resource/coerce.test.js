import { describe, expect, it } from 'vitest'
import { coerceNumbers } from './coerce'

describe('coerceNumbers', () => {
  it('turns decimal strings into numbers', () => {
    expect(coerceNumbers('1234.56')).toBe(1234.56)
    expect(coerceNumbers('-40')).toBe(-40)
    expect(coerceNumbers('0')).toBe(0)
    expect(coerceNumbers('0.00')).toBe(0)
  })

  it('walks objects and arrays', () => {
    expect(coerceNumbers({
      unassigned: '120.50',
      funds: [{ id: 1, name: 'Groceries', balance: '-12.00' }],
    })).toEqual({
      unassigned: 120.5,
      funds: [{ id: 1, name: 'Groceries', balance: -12 }],
    })
  })

  it('leaves dates and datetimes alone', () => {
    expect(coerceNumbers('2026-08-01')).toBe('2026-08-01')
    expect(coerceNumbers('2026-08-01T09:30:00')).toBe('2026-08-01T09:30:00')
  })

  it('leaves non-numeric strings alone', () => {
    expect(coerceNumbers('')).toBe('')
    expect(coerceNumbers('  ')).toBe('  ')
    expect(coerceNumbers('Groceries')).toBe('Groceries')
    expect(coerceNumbers('12abc')).toBe('12abc')
    expect(coerceNumbers('1e5')).toBe('1e5')
  })

  it('leaves zero-padded strings alone, so account masks stay masks', () => {
    expect(coerceNumbers('0042')).toBe('0042')
    expect(coerceNumbers({ mask: '0000' })).toEqual({ mask: '0000' })
  })

  it('leaves digit strings too long to survive a round trip alone', () => {
    expect(coerceNumbers('12345678901234567890')).toBe('12345678901234567890')
  })

  it('passes through non-strings untouched', () => {
    expect(coerceNumbers(null)).toBe(null)
    expect(coerceNumbers(7)).toBe(7)
    expect(coerceNumbers(true)).toBe(true)
  })

  it('coerces map-shaped values, not just fixed fields', () => {
    // /dashboard/trends returns { categories: { Housing: "1200.00" } }
    expect(coerceNumbers({ categories: { Housing: '1200.00' } }))
      .toEqual({ categories: { Housing: 1200 } })
  })
})
