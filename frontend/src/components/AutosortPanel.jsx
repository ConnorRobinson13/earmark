import { useState } from 'react'
import { api, fmt } from '../api'
import { keys, useInvalidate, useResource, writes } from '../resource'
import Modal from './Modal'
import ErrorCard from './ErrorCard'
import { Icon } from './Icons'

/**
 * AI auto-sort, as a human-in-the-loop review.
 *
 * The server proposes a fund for each pending inbox purchase; this panel shows
 * those proposals and applies only the rows the user confirms. Each row can be
 * re-pointed to a different fund, or left without one, before it is confirmed.
 * Guarantees, all enforced by the backend's suggest/confirm split:
 *
 *   - asking for suggestions writes nothing — it is a read-only proposal;
 *   - no row is approved until the user clicks Confirm, and only the rows
 *     checked at that point, each with the fund shown on it;
 *   - the OpenRouter key never reaches the client — `status` reports configured
 *     or not, and that is all the browser learns about it.
 *
 * When the server reports the feature off (no key), the action is shown
 * disabled rather than hidden, so it is clear the capability exists but is not
 * configured.
 */
export default function AutosortPanel() {
  const statusRes = useResource(keys.autosortStatus())
  const fundsRes = useResource(keys.funds())
  const invalidate = useInvalidate()

  // null = the review modal is closed; an array = open on those suggestions.
  const [suggestions, setSuggestions] = useState(null)
  // The fund each row will be approved into, by inbox id. null = no fund yet.
  const [funds, setFunds] = useState(() => new Map())
  // The rows that will be approved. A row with no fund is never in here.
  const [chosen, setChosen] = useState(() => new Set())
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [applied, setApplied] = useState(null)

  const status = statusRes.data
  const enabled = status?.enabled === true
  // Until status settles — whether it lands or fails — we claim neither state
  // and keep the button inert rather than flicker between enabled and off.
  const known = !!status || !!statusRes.error
  const fundOptions = fundsRes.data || []

  async function openReview() {
    setBusy(true)
    setErr(null)
    setApplied(null)
    try {
      const res = await api.autosort.suggestions()
      const list = res.suggestions || []
      setSuggestions(list)
      setFunds(new Map(list.map(s => [s.inbox_id, s.suggested_fund_id ?? null])))
      // Rows the model proposed a fund for start checked; rows it could not
      // place start unchecked until the user picks a fund. Nothing is applied by
      // opening the list — the user still confirms.
      setChosen(new Set(list.filter(s => s.suggested_fund_id != null).map(s => s.inbox_id)))
    } catch (e) {
      setErr(e)
    } finally {
      setBusy(false)
    }
  }

  function close() {
    setSuggestions(null)
    setFunds(new Map())
    setChosen(new Set())
    setErr(null)
  }

  function toggle(id) {
    setChosen(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  // Changing a row's fund re-points it. Picking a fund checks the row, because
  // choosing one is a decision to approve it; clearing the fund unchecks it,
  // because a row with no fund cannot be approved.
  function pickFund(id, fundId) {
    setFunds(prev => new Map(prev).set(id, fundId))
    setChosen(prev => {
      const next = new Set(prev)
      if (fundId == null) next.delete(id)
      else next.add(id)
      return next
    })
  }

  async function confirm(e) {
    e.preventDefault()
    const changes = suggestions
      .filter(s => chosen.has(s.inbox_id))
      .map(s => ({ inbox_id: s.inbox_id, fund_id: funds.get(s.inbox_id) }))
    if (changes.length === 0) return
    setBusy(true)
    setErr(null)
    try {
      const res = await api.autosort.confirm(changes)
      invalidate(writes.autosort)
      setApplied(res.updated?.length ?? changes.length)
      close()
    } catch (e) {
      setErr(e)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="autosort-bar">
      <button
        type="button"
        className="btn sm"
        onClick={openReview}
        disabled={!known || !enabled || busy}
        title={enabled
          ? 'Let AI propose funds for your pending purchases to review'
          : 'Auto-sort is not configured on the server'}
      >
        <Icon name="spark" /> {busy && suggestions === null ? 'Finding…' : 'Auto-sort'}
      </button>

      {known && !enabled && (
        <span className="small muted autosort-off">
          Auto-sort is unavailable — not configured on the server.
        </span>
      )}
      {applied != null && (
        <span className="small muted" role="status">
          Assigned {applied} transaction{applied === 1 ? '' : 's'}.
        </span>
      )}
      {/* An error from fetching suggestions: shown inline since there is no
          modal yet. A confirm error is shown inside the modal instead. */}
      {err && suggestions === null && <ErrorCard error={err} />}

      {suggestions !== null && (
        <Modal
          title="Review auto-sort"
          onClose={busy ? undefined : close}
          onSubmit={confirm}
        >
          {suggestions.length === 0 ? (
            <p className="muted">
              No suggestions right now — there are no pending purchases to sort.
            </p>
          ) : (
            <>
              <p className="small muted autosort-intro">
                Nothing is approved until you confirm. Check the rows to approve,
                and change any fund with its dropdown. A row with no fund stays
                unchecked until you pick one.
              </p>
              <ul className="autosort-list">
                {suggestions.map(s => {
                  const on = chosen.has(s.inbox_id)
                  const fundId = funds.get(s.inbox_id) ?? ''
                  const merchant = s.merchant || '(no merchant)'
                  return (
                    <li key={s.inbox_id} className={`autosort-row ${on ? '' : 'off'}`}>
                      <input
                        type="checkbox"
                        aria-label={`Approve ${merchant}`}
                        checked={on}
                        disabled={fundId === ''}
                        onChange={() => toggle(s.inbox_id)}
                      />
                      <span className="as-body">
                        <span className="as-merchant">{merchant}</span>
                        <span className="as-meta">
                          {s.date} · {fmt(Math.abs(Number(s.amount)))}
                        </span>
                      </span>
                      <select
                        className="as-pick"
                        aria-label={`Fund for ${merchant}`}
                        value={fundId}
                        onChange={e => pickFund(s.inbox_id, Number(e.target.value) || null)}
                      >
                        <option value="">No fund</option>
                        {fundOptions.map(f => (
                          <option key={f.id} value={f.id}>{f.name}</option>
                        ))}
                      </select>
                    </li>
                  )
                })}
              </ul>
            </>
          )}

          {err && <ErrorCard error={err} />}

          <div className="actions">
            <button type="button" className="btn" onClick={close} disabled={busy}>
              Cancel
            </button>
            <button type="submit" className="btn primary" disabled={busy || chosen.size === 0}>
              {busy ? 'Assigning…' : `Confirm${chosen.size ? ` ${chosen.size}` : ''}`}
            </button>
          </div>
        </Modal>
      )}
    </div>
  )
}
