/**
 * Faint Conway's Game of Life running on a fixed, full-viewport canvas behind
 * the whole app. Content sits above it (see `.app-layer`); solid card and
 * surface backgrounds occlude it, so it reads as an ambient field in the open.
 *
 * Living cells are ink. A cell that comes to life on a tick is drawn in the
 * accent for that tick only and settles to ink on the next one, so the one
 * flash of colour is spent on the rules actually firing rather than on a
 * constant wash of brand red.
 *
 * The rules themselves live in ../lib/life, pure and tested. What is left here
 * is the part that genuinely needs a browser: sizing, seeding, the timer and
 * the paint. Fainter here (opacity 0.05) than on the portfolio — this is a data
 * dashboard, not a reading site.
 */

import { useEffect, useRef } from 'react'
import { birthsBetween, population, stepField } from '../lib/life'

export default function SiteLife() {
  const canvasRef = useRef(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const CELL = 26
    const DOT = 3.4
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches

    // Read off the element so the backdrop follows the theme's tokens rather
    // than carrying its own copy of the palette.
    const token = (name, fallback) =>
      getComputedStyle(canvas).getPropertyValue(name).trim() || fallback
    // Earmark's ink token is named --text; fall back through --ink for parity
    // with the portfolio, then to the literal.
    const INK = token('--ink', '') || token('--text', '#111113')
    const ACCENT = token('--accent', '#9e1b23')

    let field = { cols: 0, rows: 0, cells: new Uint8Array(0) }
    // Which cells came to life on the last tick, laid out like the field.
    let born = new Uint8Array(0)

    const seed = (cols, rows) => {
      const cells = new Uint8Array(cols * rows)
      for (let i = 0; i < cells.length; i++) cells[i] = Math.random() < 0.24 ? 1 : 0
      field = { cols, rows, cells }
      // A fresh field has no previous generation, so nothing was born into it
      // and nothing flashes — the accent only ever marks the rules firing.
      born = new Uint8Array(cells.length)
    }

    const step = () => {
      const next = stepField(field)
      born = birthsBetween(field, next)
      field = next
      // Re-seed if the board stagnates or dies out, so it never freezes empty.
      if (population(field) < field.cells.length * 0.03) seed(field.cols, field.rows)
    }

    const draw = () => {
      const { cols, rows, cells } = field
      ctx.save()
      ctx.setTransform(1, 0, 0, 1, 0, 0)
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      ctx.restore()

      // Two passes over the field rather than one, so `fillStyle` is set twice
      // a frame instead of once a cell.
      for (const pass of [
        { colour: INK, drawsNewborn: false },
        { colour: ACCENT, drawsNewborn: true },
      ]) {
        ctx.fillStyle = pass.colour
        for (let y = 0; y < rows; y++) {
          for (let x = 0; x < cols; x++) {
            const i = y * cols + x
            if (!cells[i] || (born[i] === 1) !== pass.drawsNewborn) continue
            ctx.beginPath()
            ctx.arc(x * CELL + CELL / 2, y * CELL + CELL / 2, DOT, 0, Math.PI * 2)
            ctx.fill()
          }
        }
      }
    }

    let raf = 0
    const resize = () => {
      const w = window.innerWidth, h = window.innerHeight
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      canvas.width = Math.max(1, Math.floor(w * dpr))
      canvas.height = Math.max(1, Math.floor(h * dpr))
      canvas.style.width = w + 'px'
      canvas.style.height = h + 'px'
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      seed(Math.ceil(w / CELL) + 1, Math.ceil(h / CELL) + 1)
      draw()
    }
    const onResize = () => {
      // Debounce so drags don't reseed on every frame.
      window.cancelAnimationFrame(raf)
      raf = window.requestAnimationFrame(resize)
    }

    resize()
    window.addEventListener('resize', onResize)
    const timer = reduce ? null : window.setInterval(() => { step(); draw() }, 700)
    return () => {
      window.removeEventListener('resize', onResize)
      window.cancelAnimationFrame(raf)
      if (timer) window.clearInterval(timer)
    }
  }, [])

  return <canvas ref={canvasRef} className="site-life" aria-hidden />
}
