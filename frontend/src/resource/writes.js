import { useCallback } from 'react'
import { useResourceStore } from './context'

/**
 * What each kind of write invalidates.
 *
 * This replaced an app-wide refresh counter. Every mounted view watched that
 * counter, so recording one transaction refetched the net-worth page, the
 * Plaid item list and everything else that happened to be mounted. Here a
 * write names the reads it can change, and only those readers refetch.
 *
 * The values are key *prefixes*, matched against `keys.js` — `/funds` reaches
 * both `keys.funds()` and `keys.fund(3)`. Naming a prefix too widely costs a
 * needless round trip; naming one too narrowly leaves a stale number on
 * screen, so where the two are in tension these lean wide.
 */

// The fund ledger. Assignments, transactions, and funds coming and going all
// land in the same rows, and the dashboard's totals, every fund's balance, a
// fund's history and the pending-settlement figures are all derived from them.
const LEDGER = ['/dashboard', '/funds', '/transactions', '/settlements']

// A write that moves a real account balance. Editing an account balance
// re-syncs the goals backed by it, and settling moves money between two
// accounts, so both reach the ledger as well as the balances themselves.
const BALANCES = ['/accounts', '/networth', ...LEDGER]

export const writes = {
  /** An assignment, a transaction, a fund created or ended, a template applied. */
  ledger: LEDGER,

  /** An inbox item approved: it leaves the inbox and lands in the ledger as a transaction. */
  inboxApproved: ['/inbox', ...LEDGER],

  /** An inbox item rejected: the row is dropped and nothing reaches the ledger. */
  inboxRejected: ['/inbox'],

  /**
   * Planned income for a month. The dashboard's plan-vs-actual cell is the
   * only reader — the trailing `?` keeps this off `/dashboard/trends`, which
   * charts past spend and cannot move when a target changes. Every dashboard
   * read is month-scoped, so every one of their keys carries the query string.
   */
  plannedIncome: ['/dashboard?'],

  /** An account added, edited, retyped or deleted; goal money marked as physically moved. */
  balances: BALANCES,

  /** The fixed-expense template rows themselves. Applying the template is a `ledger` write, not this one. */
  template: ['/templates'],

  /**
   * A Plaid link, unlink or sync: a changed item list, new inbox items, and
   * refreshed account balances — which the dashboard's net-cash tile reads,
   * even though nothing has reached the fund ledger until an item is approved.
   */
  plaid: ['/plaid', '/inbox', '/accounts', '/networth', '/dashboard'],

  /** The seed reset replaces the database, so nothing on screen survives it. */
  everything: [''],
}

/**
 * Returns `invalidate(prefixes)` — pass one of the entries in `writes` after a
 * write settles, and every reader of a matching key refetches.
 */
export function useInvalidate() {
  const store = useResourceStore()
  return useCallback((prefixes) => {
    for (const prefix of prefixes) store.invalidate(prefix)
  }, [store])
}
