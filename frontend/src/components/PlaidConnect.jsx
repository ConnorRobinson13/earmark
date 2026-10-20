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
      .catch(e => setError(e))
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
      setError(e)
    } finally {
      setBusy(false)
    }
  }, [onLinked])

  const { open, ready } = usePlaidLink({
    token: linkToken,
    onSuccess,
    onExit: (err) => { if (err) setError(err.display_message || err.error_message || String(err)) },
  })

  const errorDetail = error?.body?.detail ?? error?.detail
  const credentialsMissing = !hasCreds
    || errorDetail?.code === 'PLAID_CREDENTIALS_NOT_CONFIGURED'
    || errorDetail === 'Plaid credentials not configured'
  if (credentialsMissing) {
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
        {error && <span className="bad small">{String(error)}</span>}
      </div>
    </div>
  )
}

/** Reauthenticate a linked Item without exchanging or exposing its access token. */
function PlaidReconnect({ item, onReconnected }) {
  const [linkToken, setLinkToken] = useState(null)
  const [openWhenReady, setOpenWhenReady] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [manualRecoveryNeeded, setManualRecoveryNeeded] = useState(false)

  const onSuccess = useCallback(async () => {
    setError('')
    try {
      await onReconnected?.(item)
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(false)
      setLinkToken(null)
    }
  }, [item, onReconnected])

  const onExit = useCallback((err) => {
    if (err) setError(err.display_message || err.error_message || String(err))
    setBusy(false)
    setLinkToken(null)
    setOpenWhenReady(false)
  }, [])

  const { open, ready } = usePlaidLink({ token: linkToken, onSuccess, onExit })

  useEffect(() => {
    if (!openWhenReady || !linkToken || !ready) return
    setOpenWhenReady(false)
    open()
  }, [linkToken, open, openWhenReady, ready])

  async function reconnect() {
    setBusy(true)
    setError('')
    setManualRecoveryNeeded(false)
    try {
      const response = await api.plaid.updateLinkToken(item.id)
      setLinkToken(response.link_token)
      setOpenWhenReady(true)
    } catch (e) {
      const detail = e?.detail
      const code = detail?.error_code
      const manualRecovery = ['ITEM_NOT_FOUND', 'INVALID_ACCESS_TOKEN'].includes(code)
      setManualRecoveryNeeded(manualRecovery)
      setError(manualRecovery ? detail.message : String(e))
      setBusy(false)
    }
  }

  return (
    <div className="stack" style={{ alignItems: 'flex-start' }}>
      {manualRecoveryNeeded ? (
        <span className="bad small" role="alert">
          Plaid cannot repair this Item in update mode. Review it before unlinking or reconnecting.
        </span>
      ) : (
        <button className="btn sm" onClick={reconnect} disabled={busy}>
          {busy ? 'Opening…' : `Reconnect ${item.institution_name || 'bank'}`}
        </button>
      )}
      {error && !manualRecoveryNeeded && <span className="bad small" role="alert">{String(error)}</span>}
    </div>
  )
}

/** List of linked institutions + their accounts. */
export function LinkedItems({ items, onUnlink, issues = [], onReconnected }) {
  if (!items || items.length === 0) return null
  return (
    <div className="stack">
      {items.map(it => {
        const issue = issues.find(row => row.id === it.id) || (
          it.error_code || it.needs_reauthentication
            ? {
                id: it.id,
                error_code: it.error_code,
                needs_reauthentication: it.needs_reauthentication,
              }
            : null
        )
        const statusUnavailable = it.status_available === false && !issue
        return (
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
            {statusUnavailable && (
              <div className="small muted" style={{ marginTop: 10 }} role="status">
                Plaid connection status is temporarily unavailable. Try syncing again.
              </div>
            )}
            {issue?.needs_reauthentication && (
              <div className="row" style={{ alignItems: 'center', gap: 10, marginTop: 10 }}>
                <span className="bad small">Sign in again to resume syncing this institution.</span>
                <div className="spacer" />
                <PlaidReconnect item={it} onReconnected={onReconnected} />
              </div>
            )}
            {issue && !issue.needs_reauthentication && (
              <div className="bad small" style={{ marginTop: 10 }} role="status">
                {issue.error_code === 'DATABASE_ERROR'
                  ? 'The app could not save this Item’s sync results. Check the backend logs.'
                  : ['ITEM_NOT_FOUND', 'INVALID_ACCESS_TOKEN'].includes(issue.error_code)
                    ? `Plaid says this link is invalid (${issue.error_code}). Review it before unlinking or reconnecting.`
                    : `Sync issue from Plaid: ${issue.error_code || 'unknown'}. Try again later.`}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
