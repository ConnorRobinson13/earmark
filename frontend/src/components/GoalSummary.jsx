import { Link } from 'react-router-dom'
import { fmt } from '../api'
import { dateLabel } from '../format'

/**
 * A goal's progress, and the card face that renders it.
 *
 * Three kinds of goal count three different ways: a savings goal counts its
 * balance up to a target, a debt counts what is still owed down to zero, and a
 * contribution goal counts this year's settlements toward an annual cap. The
 * dashboard's mini card and the goals page's card each worked that out for
 * themselves, and had drifted — the dashboard measured the minimum monthly
 * payment from the month you were looking at, the goals page from today.
 */

/**
 * The numbers behind one goal's progress bar, as of `month` (YYYY-MM-01).
 *
 * `minMonthly` is what has to go in each month to finish on time; null when
 * the goal has no deadline, or is already there.
 */
export function goalProgress(goal, month) {
  const isContribution = goal.goal_type === 'contribution'
  const isDebt = goal.goal_type === 'debt'
  const target = goal.target ?? 0
  const progressValue = isContribution ? (goal.contribution_ytd ?? 0) : goal.balance
  const pct = target > 0 ? Math.min(100, Math.max(0, (progressValue / target) * 100)) : 0
  const remaining = Math.max(0, target - progressValue)
  // A debt's own fixed payment includes interest, so it beats anything we
  // could estimate from the payoff date.
  const fixedPayment = isDebt && goal.min_payment != null ? goal.min_payment : null
  const minMonthly = fixedPayment ?? monthlyToFinish(remaining, goal.target_date, month)
  return { isContribution, isDebt, target, progressValue, pct, remaining, fixedPayment, minMonthly }
}

/**
 * Principal only — ignores interest, and counts `fromMonth` itself as the
 * first of the payments.
 */
function monthlyToFinish(remaining, targetDate, fromMonth) {
  if (!targetDate || remaining <= 0) return null
  const [fy, fm] = fromMonth.split('-').map(Number)
  const [ty, tm] = targetDate.split('-').map(Number)
  const months = Math.max(1, (ty - fy) * 12 + (tm - fm) + 1)
  return remaining / months
}

/**
 * Heading, headline amount, progress bar and footer — the half of a goal card
 * that is the same in both places it appears. What sits below it (the assign
 * row on the dashboard, the account picker and contribute form on the goals
 * page) is each caller's own.
 *
 * `linkTo` wraps the heading in a link, which the dashboard's mini cards want
 * and the goals page's own cards do not.
 */
export default function GoalSummary({ goal, progress, linkTo }) {
  const { isContribution, isDebt, target, progressValue, pct, remaining } = progress
  const kind = isContribution ? 'contribution' : isDebt ? 'debt' : 'savings'

  const heading = (
    <>
      <div className="row" style={{ gap: 6, alignItems: 'center' }}>
        <div className="name">{goal.name}</div>
        <span className={`goal-badge ${kind}`}>{kind}</span>
      </div>
      <div className="deadline">
        {goal.target_date
          ? `${isDebt ? 'payoff by' : 'by'} ${dateLabel(goal.target_date)}`
          : 'no deadline'}
      </div>
    </>
  )

  return (
    <>
      {linkTo
        ? <Link to={linkTo} style={{ color: 'inherit', display: 'block' }}>{heading}</Link>
        : <div>{heading}</div>}

      <div className="amount-row">
        <div className="big">{fmt(isDebt ? remaining : progressValue)}</div>
        <div className="target">
          {isContribution
            ? `of ${fmt(target)} ${goal.contribution_year ?? ''}`
            : isDebt ? `of ${fmt(target)} owed` : `of ${fmt(target)}`}
        </div>
      </div>

      <div className="progress-track">
        <div className="progress-fill" style={{ width: `${pct}%` }} />
      </div>
      <div className="footer-row">
        <span>{pct.toFixed(0)}% {isContribution ? 'contributed' : isDebt ? 'paid off' : 'complete'}</span>
        <span>{isDebt ? (remaining > 0 ? `${fmt(remaining)} left` : 'paid off 🎉') : `${fmt(remaining)} to go`}</span>
      </div>
    </>
  )
}
