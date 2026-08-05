import { useEffect, useState, useCallback } from 'react'
import { usePlaidLink } from 'react-plaid-link'
import { api, fmt } from '../api'
import { relativeTime } from '../format'
import { Icon } from './Icons'

/**
 * "Connect a bank" via Plaid Link.
 *
 * Lifecycle:
 *  1. Mount → fetch link_token from /plaid/link-token
 *  2. User clicks button → Plaid Link modal opens (Plaid-hosted UI)
 *  3. On success → POST public_token + institution name to /plaid/exchange
 *     → backend stores Item + auto-pulls accounts (with names + balances)
 *  4. Parent's onLinked() refreshes the items list + account cards
 */
export default function PlaidConnect({ onLinked, hasCreds, disabled }) {
  const [linkToken, setLinkToken] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!hasCreds) return
    api.plaid.linkToken()
      .then(r => setLinkToken(r.link_token))
      .catch(e => setError(String(e)))
  }, [hasCreds])

  const onSuccess = useCallback(async (public_token, metadata) => {
    setBusy(true); setError('')
    try {
      await api.plaid.exchange(public_token, metadata?.institution?.name)
      onLinked?.()
      // get a fresh token for the next link, since each one is single-use
      const r = await api.plaid.linkToken()
      setLinkToken(r.link_token)
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(false)
    }
  }, [onLinked])

  const { open, ready } = usePlaidLink({
    token: linkToken,
    onSuccess,
    onExit: (err) => { if (err) setError(err.display_message || err.error_message || String(err)) },
  })

  if (!hasCreds) {
    return (
      <div className="muted small">
        Plaid credentials not configured. Add <code>PLAID_CLIENT_ID</code> and{' '}
        <code>PLAID_SECRET</code> to your <code>.env</code> and restart the backend.
      </div>
    )
  }

  return (
    <div className="stack">
      <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
        <button
          className="btn primary"
          onClick={() => open()}
          disabled={!ready || busy || !linkToken || disabled}
          title={disabled ? 'Trial limit reached (10 Items). Unlinking does not free slots.' : ''}
        >
          <Icon name="plus" /> {busy ? 'Linking…' : disabled ? 'Trial cap reached' : 'Connect a bank'}
        </button>
        {error && <span className="bad small">{error}</span>}
      </div>
    </div>
  )
}

/** List of linked institutions + their accounts. */
export function LinkedItems({ items, onUnlink }) {
  if (!items || items.length === 0) return null
  return (
    <div className="stack">
      {items.map(it => (
        <div key={it.id} className="card" style={{ padding: 14 }}>
          <div className="row" style={{ alignItems: 'center', gap: 10 }}>
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 500 }}>{it.institution_name || 'Unnamed institution'}</div>
              <div className="small muted">item {it.item_id.slice(0, 12)}…</div>
            </div>
            <button className="btn ghost sm" onClick={() => onUnlink(it.id, it.institution_name)} title="Unlink">
              <Icon name="x" size={14} /> Unlink
            </button>
          </div>
          {it.accounts.length > 0 && (
            <div className="stack" style={{ marginTop: 10, gap: 4 }}>
              {it.accounts.map(a => (
                <div key={a.id} className="row" style={{ gap: 10, fontSize: 13 }}>
                  <span style={{ color: 'var(--text-2)' }}>{a.name}</span>
                  <span className="muted small">({a.type})</span>
                  <div className="spacer" />
                  <span className="num" style={{ fontWeight: 500 }}>{fmt(a.current_balance)}</span>
                  {a.last_synced_at && (
                    <span className="muted small">· synced {relativeTime(a.last_synced_at)}</span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
