import { useState } from 'react'
import { api } from '../api'
import { keys, useInvalidate, useResource, writes } from '../resource'

const NEW = '__new__'

/**
 * Chooses a category from the managed list, or creates one and chooses it.
 *
 * The value is a category id (or null for none), so a fund can only ever point
 * at a category that exists. Creating one happens inline, the way a new fund is
 * added: pick "+ New category…", type a name, and it is saved and selected.
 */
export default function CategoryPicker({ value, onChange, disabled = false }) {
  const categoriesRes = useResource(keys.categories())
  const categories = categoriesRes.data ?? []
  const invalidate = useInvalidate()
  const [adding, setAdding] = useState(false)
  const [name, setName] = useState('')
  const [err, setErr] = useState('')

  function pick(e) {
    if (e.target.value === NEW) {
      setAdding(true)
      return
    }
    onChange(e.target.value ? Number(e.target.value) : null)
  }

  async function create() {
    const trimmed = name.trim()
    if (!trimmed) return
    setErr('')
    try {
      const made = await api.categories.create({ name: trimmed })
      invalidate(writes.categories)
      setAdding(false)
      setName('')
      onChange(made.id)
    } catch (e) {
      setErr(String(e))
    }
  }

  return (
    <span className="category-picker">
      <select
        aria-label="Category"
        value={value ?? ''}
        disabled={disabled}
        onChange={pick}
      >
        <option value="">No category</option>
        {categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        <option value={NEW}>+ New category…</option>
      </select>

      {adding && (
        <span className="category-new">
          <input
            autoFocus
            aria-label="New category name"
            placeholder="e.g. Housing"
            value={name}
            onChange={e => setName(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter') { e.preventDefault(); create() }
              if (e.key === 'Escape') { setAdding(false); setErr('') }
            }}
          />
          <button type="button" className="btn sm primary" onClick={create}>Add</button>
          <button type="button" className="btn sm ghost" onClick={() => { setAdding(false); setErr('') }}>
            Cancel
          </button>
        </span>
      )}

      {err && <span className="bad small">{err}</span>}
    </span>
  )
}
