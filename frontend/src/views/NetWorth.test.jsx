import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { renderApp, fund, emptyDashboard, shellRoutes, SHELL_KEYS } from '../test/renderApp'
import { ApiError, keys } from '../resource'
import { api } from '../api'
import { thisMonth } from '../components/MonthSelector'

const MONTH = thisMonth()

const NETWORTH = {
  total: '48250.00',
  liquid: '4200.00',
  investment: '42000.00',
  emergency_fund: '6000.00',
  credit_debt: '350.00',
  loan_debt: '3600.00',
  accounts: [
    { id: 1, name: 'Everyday checking', type: 'checking', balance: '2200.00' },
    { id: 3, name: 'Vanguard', type: 'investment', balance: '42000.00' },
  ],
}

const HISTORY = [
  { month: '2026-06-01', total: '45000.00' },
  { month: '2026-07-01', total: '46500.00' },
  { month: '2026-08-01', total: '48250.00' },
]

// Rent and groceries count toward the runway; the streaming subscription does not.
const DASH_FUNDS = [
  fund({ id: 1, name: 'Rent', category: 'Housing', assigned_this_month: '1800.00' }),
  fund({ id: 2, name: 'Groceries', category: 'Food', assigned_this_month: '600.00' }),
  fund({ id: 3, name: 'Netflix', category: 'Subscriptions', assigned_this_month: '20.00' }),
]

/**
 * The exact parameters the web app sends for the projection's default dials.
 *
 * `mcp/tests/test_server.py` pins this same set from the MCP tool's side, and
 * `backend/tests/test_retirement_api.py` pins what the backend makes of it.
 * Between them: the same question asked from either client reaches the same
 * endpoint with the same assumptions, and so comes back with the same number.
 * Keep the three in step.
 */
const SHARED_PARAMS = {
  current_age: 28,
  retire_age: 65,
  annual_return_pct: 8,
  monthly_contribution: 583,
  contribution_growth_pct: 3,
  inflation_pct: 2.5,
}

/** The dials the view starts on, before anything is saved to localStorage. */
const DEFAULT_DIALS = {
  currentAge: 28,
  retireAge: 65,
  annualReturnPct: 8,
  monthlyContribution: 583,
  contributionGrowthPct: 3,
  inflationPct: 2.5,
}

const PROJECTION_KEY = keys.retirementProjection(DEFAULT_DIALS)

/**
 * A projection as the backend serialises it. Its starting balance is
 * deliberately *not* the net-worth read's investment total, and its final value
 * is not what this recurrence would produce from either — so a panel that went
 * back to compounding locally would fail every assertion below.
 */
const PROJECTION = {
  current_age: 28,
  retire_age: 65,
  years: 37,
  annual_return_pct: '8',
  monthly_contribution: '583',
  contribution_growth_pct: '3',
  inflation_pct: '2.5',
  starting_balance: '50000.00',
  total_contributed: '458000.00',
  compounded_growth: '492000.00',
  final_nominal: '1000000.00',
  final_real: '400000.00',
  series: [
    { year: 0, age: 28, nominal: '50000.00', real: '50000.00', contributed: '0.00' },
    { year: 37, age: 65, nominal: '1000000.00', real: '400000.00', contributed: '458000.00' },
  ],
}

function routes(overrides = {}) {
  return {
    ...shellRoutes({ dashboard: emptyDashboard({ funds: DASH_FUNDS }) }),
    [keys.networth()]: NETWORTH,
    [keys.networthHistory()]: HISTORY,
    [PROJECTION_KEY]: PROJECTION,
    ...overrides,
  }
}

describe('NetWorth', () => {
  // Opening the page captures a snapshot, so every test here makes that write.
  // The dials persist to localStorage, so a test that moves one would hand the
  // next test a different projection key if it were not cleared between them.
  beforeEach(() => {
    localStorage.clear()
    vi.spyOn(api, 'networthSnapshot').mockResolvedValue({})
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders the current position against a stub adapter', async () => {
    renderApp(routes(), { route: '/networth' })

    expect(await screen.findByText('$48,250.00')).toBeTruthy()
    expect(screen.getByText('$6,000.00')).toBeTruthy()   // emergency
    expect(screen.getByText('Vanguard')).toBeTruthy()
    expect(screen.getByText(/\$350\.00 in card debt/)).toBeTruthy()
  })

  it('computes the emergency runway from the month in the top bar', async () => {
    renderApp(routes(), { route: '/networth' })

    // 6000 ÷ (1800 rent + 600 groceries) = 2.5 months. Netflix is excluded.
    expect(await screen.findByText(/\$2,400\.00\/mo needs/)).toBeTruthy()
    expect(document.querySelector('.runway-num .big').textContent).toBe('2.5')
  })

  it('records this month before it asks for the history', async () => {
    // Capturing the snapshot is what makes history accrue — GET /networth
    // writes nothing — and it has to happen first, or the line comes back a
    // point short of the total in the hero above it.
    let capturedYet = false
    vi.spyOn(api, 'networthSnapshot').mockImplementation(async () => {
      capturedYet = true
      return {}
    })
    // A database whose history only holds this month's point once it has been
    // captured — so reading too early draws the empty state, not the line.
    renderApp(routes({
      [keys.networthHistory()]: () => (capturedYet ? HISTORY : []),
    }), { route: '/networth' })

    expect(await screen.findByText(/since Jun 26/)).toBeTruthy()
    expect(screen.queryByText(/Tracking starts now/)).toBe(null)
  })

  it('captures again on a second visit rather than skipping it', async () => {
    // Idempotency is the endpoint's job — capturing twice in a month replaces
    // that month's row, which `backend/tests/test_networth_api.py` pins — so
    // the caller's job is simply to ask every time the page is opened, and a
    // month spanning several visits still ends up with one point.
    const { unmount } = renderApp(routes(), { route: '/networth' })
    await screen.findByText(/since Jun 26/)
    unmount()

    renderApp(routes(), { route: '/networth' })
    await screen.findByText(/since Jun 26/)

    expect(api.networthSnapshot).toHaveBeenCalledTimes(2)
  })

  it('still draws the trend when the capture fails', async () => {
    // The history that already exists is worth showing either way.
    vi.spyOn(api, 'networthSnapshot').mockRejectedValue(new Error('503: no'))

    renderApp(routes(), { route: '/networth' })

    expect(await screen.findByText(/since Jun 26/)).toBeTruthy()
  })

  it('draws the trend once there are two snapshots', async () => {
    renderApp(routes(), { route: '/networth' })

    expect(await screen.findByText(/since Jun 26/)).toBeTruthy()
    expect(screen.queryByText(/Tracking starts now/)).toBe(null)
  })

  it('explains the empty trend when there is only one snapshot', async () => {
    renderApp(routes({ [keys.networthHistory()]: [HISTORY[0]] }), { route: '/networth' })

    expect(await screen.findByText(/Tracking starts now/)).toBeTruthy()
  })

  it('shows the server message when the net-worth read fails', async () => {
    renderApp(routes({
      [keys.networth()]: new ApiError(503, { detail: 'Database is asleep' }, keys.networth()),
    }), { route: '/networth' })

    expect(await screen.findByText('Database is asleep')).toBeTruthy()
  })

  it('keeps the position standing when only the runway read fails', async () => {
    renderApp(routes({
      [keys.dashboard(MONTH)]: new ApiError(500, { detail: 'dashboard down' }, keys.dashboard(MONTH)),
    }), { route: '/networth' })

    await screen.findByText('$48,250.00')
    expect(screen.queryByText(/months covered/)).toBe(null)
  })

  it('reads four keys, one of them shared with the shell', async () => {
    const { adapter } = renderApp(routes(), { route: '/networth' })

    await screen.findByText(/since Jun 26/)
    const own = adapter.requested.filter(k => !SHELL_KEYS.includes(k))
    expect([...new Set(own)].sort()).toEqual(
      [keys.networth(), keys.networthHistory(), PROJECTION_KEY].sort(),
    )
  })

  it('asks the backend for the projection under the dials on screen', async () => {
    const { adapter } = renderApp(routes(), { route: '/networth' })

    await screen.findByText(/≈ \$1,000,000\.00 nominal/)
    const asked = adapter.requested.find(k => k.startsWith('/retirement/projection'))
    const params = new URL(asked, 'http://backend').searchParams
    expect(Object.fromEntries([...params].map(([k, v]) => [k, Number(v)]))).toEqual(SHARED_PARAMS)
  })

  it('renders the projection the backend sent rather than one of its own', async () => {
    renderApp(routes(), { route: '/networth' })

    // Today's dollars is the default view, so the server's `final_real` leads.
    expect(await screen.findByText(/≈ \$1,000,000\.00 nominal/)).toBeTruthy()
    expect(document.querySelector('.plan-sticky .big').textContent).toBe('$400,000.00')
    expect(screen.getByText(/after 2\.5% inflation/)).toBeTruthy()
    // The starting balance is the endpoint's, not the net-worth read's.
    expect(screen.getByText('$50,000.00')).toBeTruthy()
    expect(screen.getByText('$458,000.00')).toBeTruthy()
    expect(screen.getByText('$492,000.00')).toBeTruthy()
    expect(screen.getByText(/in 37 years at 8% return, contributions growing 3%\/yr/)).toBeTruthy()
  })

  it('asks once for a slider dragged across several positions', async () => {
    // Every dial is in the key, so an undebounced drag would ask the backend
    // for each value it passed through on the way to the one being asked.
    const { adapter } = renderApp(routes({
      [keys.retirementProjection({ ...DEFAULT_DIALS, currentAge: 31 })]: PROJECTION,
    }), { route: '/networth' })
    await screen.findByText(/≈ \$1,000,000\.00 nominal/)

    const currentAge = document.querySelectorAll('.proj-slider')[0]
    for (const age of [29, 30, 31]) {
      fireEvent.change(currentAge, { target: { value: String(age) } })
    }

    const projections = () => adapter.requested.filter(k => k.startsWith('/retirement/projection'))
    await waitFor(() => expect(projections()).toHaveLength(2))
    expect(projections()[1]).toContain('current_age=31')
    // Give the ones that were skipped a chance to show up late.
    await waitFor(() => expect(projections()).toHaveLength(2))
  })

  it('asks the same question the MCP tool asks', () => {
    // The MCP tool pins this same set from its side, in
    // `mcp/tests/test_server.py`, against the same backend test file. Nothing
    // else would notice if one client quietly started asking something else.
    const backendTest = resolve(__dirname, '../../../backend/tests/test_retirement_api.py')
    if (!existsSync(backendTest)) return // the backend is not in this checkout
    const source = readFileSync(backendTest, 'utf8')

    for (const [name, value] of Object.entries(SHARED_PARAMS)) {
      expect(source).toContain(`"${name}": ${value},`)
    }
  })

  it('says so when the projection is the only read that failed', async () => {
    renderApp(routes({
      [PROJECTION_KEY]: new ApiError(500, { detail: 'projection unavailable' }, PROJECTION_KEY),
    }), { route: '/networth' })

    await screen.findByText('$48,250.00')
    expect(screen.getByText('projection unavailable')).toBeTruthy()
  })
})
