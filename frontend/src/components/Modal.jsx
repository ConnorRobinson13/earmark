import { useEffect, useId } from 'react'

/**
 * The dialog every form in the app opens in.
 *
 * There were four of these written out by hand — new fund, new goal, add
 * account, quick add — each a backdrop div, a form, an h2 and the same
 * `stopPropagation` so a click inside did not count as a click outside. They
 * had drifted in the ways hand-copied markup does: none of them closed on
 * Escape, none announced itself as a dialog, and the quick-add one alone put
 * its heading in a row.
 *
 * On a phone the same element is a bottom sheet — that is entirely the
 * stylesheet's doing (`.modal` under the 720px breakpoint); the markup is one
 * shape either way.
 *
 * `action` is an optional control shown beside the heading, which is what
 * quick add's expense/income toggle wants.
 */
export default function Modal({ title, action, onClose, onSubmit, children }) {
  const titleId = useId()

  // On the document rather than the dialog: the key has to work wherever focus
  // happens to be, including before anything inside has been focused at all.
  useEffect(() => {
    if (!onClose) return
    function onKey(e) {
      if (e.key === 'Escape') {
        e.stopPropagation()
        onClose()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <form
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={e => e.stopPropagation()}
        onSubmit={onSubmit}
      >
        <div className="modal-head">
          <h2 id={titleId}>{title}</h2>
          {action}
        </div>
        {children}
      </form>
    </div>
  )
}
