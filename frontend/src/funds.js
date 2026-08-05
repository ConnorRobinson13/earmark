/**
 * What kind a fund is — asked in one place.
 *
 * `kind` rides on every fund payload, so the backend has already answered this.
 * What had no home on this side of the wire was the reading of it: the
 * dashboard, the goals page, the settings page, the net-worth runway and the
 * fund detail header each spelled a comparison out for themselves, and not the
 * same way — `kind === 'operational'` in the dashboard, `kind !== 'operational'`
 * in the runway.
 *
 * Those two agree, and they would agree even about a kind neither had heard of:
 * the runway's sits in a rejection clause, so an unknown kind falls out of the
 * runway as surely as it falls out of the dashboard. The problem is not that
 * they disagree. It is that agreeing was luck — five views had each already
 * settled what a third kind would mean, separately, and nobody was asked. One
 * home makes that one decision, in a place where it can be seen and changed.
 *
 * Both predicates test for what a fund is rather than for what it is not, so a
 * kind neither knows is in neither half.
 */
const OPERATIONAL = 'operational'
const GOAL = 'goal'

/** A monthly spending bucket — groceries, rent, subscriptions. */
export function isOperational(fund) {
  return fund.kind === OPERATIONAL
}

/** A long-term bucket — savings, a debt payoff, an annual contribution cap. */
export function isGoal(fund) {
  return fund.kind === GOAL
}
