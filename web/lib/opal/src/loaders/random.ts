// Seeded randomness for loaders that pick their own shape.

type NonEmpty<T> = readonly [T, ...T[]];

/**
 * A pseudo-random generator seeded from a string. Seeded from `useId`, it
 * gives each loader its own shape, the same on the server and the client and
 * on every render.
 */
function seededRandom(seed: string): () => number {
  let state = 2166136261;
  for (let index = 0; index < seed.length; index++) {
    state = Math.imul(state ^ seed.charCodeAt(index), 16777619);
  }
  return () => {
    state = (state + 0x6d2b79f5) | 0;
    let value = Math.imul(state ^ (state >>> 15), 1 | state);
    value = (value + Math.imul(value ^ (value >>> 7), 61 | value)) ^ value;
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
  };
}

function pick<T>(items: NonEmpty<T>, random: () => number): T {
  return items[Math.floor(random() * items.length)] ?? items[0];
}

export { seededRandom, pick, type NonEmpty };
