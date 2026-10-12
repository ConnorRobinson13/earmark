import { useState } from 'react'
import { api, fmt } from '../api'
import { keys, useInvalidate, useResource, writes } from '../resource'
import Modal from './Modal'
import ErrorCard from './ErrorCard'
import { Icon } from './Icons'

/**
 * AI auto-sort, as a human-in-the-loop review.
 *
 * The server proposes a fund for each unsorted expense; this panel shows those
 * proposals and applies only the ones the user confirms. Three guarantees it
 * leans on, all enforced by the backend's suggest/confirm split:
 *
 *   - asking for suggestions writes nothing — it is a read-only proposal;
 *   - no assignment is applied until the user clicks Confirm, and only for the
 *     rows still checked at that point;
 *   - the OpenRouter key never reaches the client — `status` reports configured
 *     or not, and that is all the browser learns about it.
 *
 * When the server reports the feature off (no key), the action is shown
 * disabled rather than hidden, so it is clear the capability exists but is not
 * configured.
 */
export default function AutosortPanel() {
  const statusRes = useResource(keys.autosortStatus())
  const invalidate = useInvalidate()

  // null = the review modal is closed; an array = open on those suggestions.
  const [suggestions, setSuggestions] = useState(null)
  const [chosen, setChosen] = useState(() => new Set())
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [applied, setApplied] = useState(null)

  const status = statusRes.data
  const enabled = status?.enabled === true
  // Until status settles — whether it lands or fails — we claim neither state
  // and keep the button inert rather than flicker between enabled and off.
  const known = !!status || !!statusRes.error

  async function openReview() {
    setBusy(true)
    setErr(null)
    setApplied(null)
    try {
      const res = await api.autosort.suggestions()
      const list = res.suggestions || []
      setSuggestions(list)
      // Every row starts checked, but nothing is applied by opening the list —
      // the user still confirms, and can uncheck any row first.
      setChosen(new Set(list.map(s => s.transaction_id)))
    } catch (e) {
      setErr(e)
    } finally {
      setBusy(false)
    }
  }

  function close() {
    setSuggestions(null)
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

  async function confirm(e) {
    e.preventDefault()
    const changes = suggestions
      .filter(s => chosen.has(s.transaction_id))
      .map(s => ({ transaction_id: s.transaction_id, fund_id: s.suggested_fund_id }))
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
          ? 'Let AI propose funds for your unsorted expenses to review'
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
              No suggestions right now — every expense already has a fund, or the
              model proposed nothing to assign.
            </p>
          ) : (
            <>
              <p className="small muted autosort-intro">
                Nothing is assigned until you confirm. Uncheck any row you don’t
                want.
              </p>
              <ul className="autosort-list">
                {suggestions.map(s => {
                  const on = chosen.has(s.transaction_id)
                  return (
                    <li key={s.transaction_id} className={`autosort-row ${on ? '' : 'off'}`}>
                      <label>
                        <input
                          type="checkbox"
                          checked={on}
                          onChange={() => toggle(s.transaction_id)}
                        />
                        <span className="as-merchant">{s.merchant || '(no merchant)'}</span>
                        <span className="as-meta">
                          {s.date} · {fmt(Math.abs(Number(s.amount)))}
                        </span>
                        <span className="as-fund">
                          <Icon name="chev_r" /> {s.suggested_fund_name}
                        </span>
                      </label>
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
