/**
 * Conway's Game of Life, as much of it as the site's mark needs.
 *
 * The mark is a glider showing two consecutive generations. The second one is
 * computed here rather than drawn by hand, so it is the real next generation
 * and not five squares that merely look like one.
 *
 * Cells are sparse coordinates on an unbounded field — there is no grid, no
 * wrapping and no edges, which is what makes "one generation on" well defined.
 *
 * The ambient backdrop in src/themes/catalog/chrome/SiteLife.tsx runs Life too,
 * on a dense wrapping Uint8Array, because it steps thousands of cells on a
 * timer. `stepField` below is that second step, living here beside the first
 * rather than inside the canvas effect so its rules and its births can be
 * tested without a canvas.
 *
 * The two representations are deliberately not folded together: five cells on
 * an open field and a wrapping full-viewport grid want opposite data
 * structures, and sharing one would cost the backdrop its tight inner loop and
 * cost the mark its edgeless field.
 */

export type Cell = readonly [x: number, y: number];

/**
 * The glider at generation 0, drawn into the 3×3 box at the origin:
 *
 *     . # .
 *     . . #
 *     # # #
 */
export const GLIDER: readonly Cell[] = [
  [1, 0],
  [2, 1],
  [0, 2],
  [1, 2],
  [2, 2],
];

const key = (x: number, y: number) => `${x},${y}`;

/**
 * The next generation. A live cell with two or three live neighbours survives;
 * a dead cell with exactly three comes to life; everything else is dead.
 *
 * Only cells adjacent to something living can change, so those are the only
 * ones considered. Output is sorted, so the same generation always renders to
 * the same markup.
 */
export function nextGeneration(cells: readonly Cell[]): Cell[] {
  const live = new Set(cells.map(([x, y]) => key(x, y)));

  // Every cell that might be alive next tick, mapped to its live-neighbour count.
  const neighbours = new Map<string, { cell: Cell; count: number }>();
  for (const [x, y] of cells) {
    for (let dy = -1; dy <= 1; dy++) {
      for (let dx = -1; dx <= 1; dx++) {
        if (dx === 0 && dy === 0) continue;
        const [nx, ny] = [x + dx, y + dy];
        const at = neighbours.get(key(nx, ny));
        if (at) at.count++;
        else neighbours.set(key(nx, ny), { cell: [nx, ny], count: 1 });
      }
    }
  }

  const next: Cell[] = [];
  for (const [at, { cell, count }] of neighbours) {
    if (count === 3 || (count === 2 && live.has(at))) next.push(cell);
  }

  return next.sort(([ax, ay], [bx, by]) => ay - by || ax - bx);
}

/**
 * A generation of the backdrop: a fixed grid of cells, row-major, one byte
 * each, 1 alive and 0 dead. The grid wraps in both axes, so the field has no
 * edge for patterns to die against.
 */
export type Field = {
  readonly cols: number;
  readonly rows: number;
  readonly cells: Uint8Array;
};

/**
 * The next generation of a wrapping field. Same rules as `nextGeneration` — two
 * or three neighbours to survive, exactly three to be born — evaluated over
 * every cell rather than only those near something living, because on a dense
 * grid that is the cheaper of the two.
 *
 * Pure: the field passed in is not touched, and the one returned is new.
 */
export function stepField({ cols, rows, cells }: Field): Field {
  const next = new Uint8Array(cells.length);
  const at = (x: number, y: number) => ((y + rows) % rows) * cols + ((x + cols) % cols);

  for (let y = 0; y < rows; y++) {
    for (let x = 0; x < cols; x++) {
      let n = 0;
      for (let dy = -1; dy <= 1; dy++)
        for (let dx = -1; dx <= 1; dx++) if (dx || dy) n += cells[at(x + dx, y + dy)];
      const alive = cells[y * cols + x];
      next[y * cols + x] = (alive && (n === 2 || n === 3)) || (!alive && n === 3) ? 1 : 0;
    }
  }

  return { cols, rows, cells: next };
}

/**
 * Which cells came to life on the step from `previous` to `current`, as a mask
 * laid out like the field itself. A cell that was already alive is a survivor,
 * not a birth, so a given cell is marked for exactly one generation however
 * long it then lives — which is what lets the backdrop flash it once.
 *
 * The two fields are expected to be consecutive generations of the same grid.
 * Across a resize they are not comparable at all, so nothing is marked rather
 * than every cell on the new grid counting as newly born.
 */
export function birthsBetween(previous: Field, current: Field): Uint8Array {
  const born = new Uint8Array(current.cells.length);
  // Dimensions, not cell count: a field reshaped to the same area holds
  // different cells at the same indices, so it is no more comparable than one
  // of a different size.
  if (previous.cols !== current.cols || previous.rows !== current.rows) return born;

  for (let i = 0; i < born.length; i++) born[i] = current.cells[i] && !previous.cells[i] ? 1 : 0;
  return born;
}

/** How many cells of a field are alive. */
export function population({ cells }: Field): number {
  let live = 0;
  for (let i = 0; i < cells.length; i++) live += cells[i];
  return live;
}
