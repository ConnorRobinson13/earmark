import { describe, expect, it } from 'vitest'
import { isGoal, isOperational } from './funds'

const ops = { id: 1, name: 'Groceries', kind: 'operational' }
const goal = { id: 2, name: 'Emergency fund', kind: 'goal' }

describe('fund kind predicates', () => {
  it('sorts the two kinds the backend has into their own halves', () => {
    expect(isOperational(ops)).toBe(true)
    expect(isOperational(goal)).toBe(false)
    expect(isGoal(goal)).toBe(true)
    expect(isGoal(ops)).toBe(false)
  })

  it('puts a kind it has never heard of in neither half', () => {
    // Each predicate asks what a fund is, never what it is not — so a third
    // kind arrives as an empty heading someone has to decide about, rather
    // than quietly counted under one of the two that already exist.
    const unknown = { id: 3, name: 'Sinking fund', kind: 'sinking' }

    expect(isOperational(unknown)).toBe(false)
    expect(isGoal(unknown)).toBe(false)
  })

  it('reads a fund list through filter, which is how every caller uses it', () => {
    const rent = { id: 4, name: 'Rent', kind: 'operational' }
    const funds = [ops, goal, rent]

    expect(funds.filter(isOperational)).toEqual([ops, rent])
    expect(funds.filter(isGoal)).toEqual([goal])
  })
})
