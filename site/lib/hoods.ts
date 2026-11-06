// Neighborhoods for the home map's picker and insights. Each property goes to the nearest of six
// centers, a rough stand-in for Jersey City's six wards (A Greenville, B West Side, C Journal Square,
// D The Heights, E Downtown, F Bergen-Lafayette). Good enough to compare areas; not official boundaries.

export interface Hood { key: string; name: string; short: string; lat: number; lon: number }

export const HOODS: Hood[] = [
  { key: "heights", name: "The Heights", short: "The Heights", lat: 40.749, lon: -74.048 },
  { key: "jsq", name: "Journal Square", short: "Journal Sq.", lat: 40.7325, lon: -74.0625 },
  { key: "downtown", name: "Downtown", short: "Downtown", lat: 40.717, lon: -74.039 },
  { key: "westside", name: "West Side", short: "West Side", lat: 40.72, lon: -74.086 },
  { key: "bergen", name: "Bergen-Lafayette", short: "Bergen-Lafayette", lat: 40.7075, lon: -74.064 },
  { key: "greenville", name: "Greenville", short: "Greenville", lat: 40.693, lon: -74.084 },
];

const K = Math.cos((40.72 * Math.PI) / 180); // shrink longitude so distances are roughly even

export function hoodOf(lat: number, lon: number): number {
  let best = 0, bd = Infinity;
  for (let i = 0; i < HOODS.length; i++) {
    const dy = lat - HOODS[i].lat, dx = (lon - HOODS[i].lon) * K;
    const d = dx * dx + dy * dy;
    if (d < bd) { bd = d; best = i; }
  }
  return best;
}

// How properties split against what most of the city saw, as whole numbers out of every 100.
export interface Split { n: number; slower: number; same: number; faster: number }

// Largest-remainder rounding, so the three parts always add up to exactly 100.
export function per100(slower: number, same: number, faster: number): Split {
  const n = slower + same + faster;
  if (!n) return { n: 0, slower: 0, same: 0, faster: 0 };
  const raw = [slower, same, faster].map((c) => (c * 100) / n);
  const out = raw.map(Math.floor);
  const order = raw.map((v, i) => [v - Math.floor(v), i] as const).sort((a, b) => b[0] - a[0]);
  for (let k = 0, left = 100 - out.reduce((a, b) => a + b, 0); k < left; k++) out[order[k][1]]++;
  return { n, slower: out[0], same: out[1], faster: out[2] };
}
