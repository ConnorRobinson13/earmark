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

  it('leaves text fields alone even when they look like numbers', () => {
    // A "529" college fund is a real thing to call a fund, and the dashboard
    // sorts categories with localeCompare.
    expect(coerceNumbers({ name: '529', category: '529', balance: '250.00' }))
      .toEqual({ name: '529', category: '529', balance: 250 })
    expect(coerceNumbers({ merchant: '76', amount: '-42.10' }))
      .toEqual({ merchant: '76', amount: -42.1 })
    expect(coerceNumbers({ notes: '100' })).toEqual({ notes: '100' })
  })

  it('leaves a list of category names alone but coerces a map keyed by them', () => {
    // Both arrive under `categories` in the /dashboard/trends response.
    expect(coerceNumbers({
      categories: ['Housing', '529'],
      months: [{ month: '2026-08-01', categories: { '529': '1200.00' }, total: '1200.00' }],
    })).toEqual({
      categories: ['Housing', '529'],
      months: [{ month: '2026-08-01', categories: { '529': 1200 }, total: 1200 }],
    })
  })

  it('leaves a cash-flow event label alone even when it is all digits', () => {
    // `label` is a fund's name, so a fund called "529" must stay a string.
    expect(coerceNumbers({
      days: [{ date: '2026-08-20', balance: '1200.00', events: [
        { kind: 'outflow', label: '529', amount: '-300.00' },
      ] }],
    })).toEqual({
      days: [{ date: '2026-08-20', balance: 1200, events: [
        { kind: 'outflow', label: '529', amount: -300 },
      ] }],
    })
  })

  it('coerces money inside arrays of records', () => {
    expect(coerceNumbers({ funds: [{ id: 1, name: 'Rent', balance: '1800.00' }] }))
      .toEqual({ funds: [{ id: 1, name: 'Rent', balance: 1800 }] })
  })
})
