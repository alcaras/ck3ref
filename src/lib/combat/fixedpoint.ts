// CK3 combat math runs on CFixedPoint with scale 100000 (confirmed: GetCombatWidth returns
// width*100000; every combat product divides by 100000 with truncation). We mirror that here:
// values are integers scaled by FX, multiply/divide truncate toward zero exactly as the game.
//
// Precision note: JS numbers are exact integers up to 2^53. Intermediate products are
// (menFixed * statFixed) ~ (army_men*1e5)*(stat*1e5). For armies up to ~1e6 men and stats up
// to ~1e3 that is ~1e11 * 1e8 = 1e19 which EXCEEDS 2^53, so fxMul routes large operands through
// the same hi/lo split the binary uses to stay exact. For typical armies (<~50k men) plain
// products stay under 2^53 and the fast path is used.

export const FX = 100000;

export const toFx = (real: number): number => Math.round(real * FX);
export const fromFx = (fx: number): number => fx / FX;

const SPLIT = 94906266; // ~2^26.5 * ... guard threshold analogous to 0xb504f333 at this scale

/** fixed-point multiply: trunc(a*b/FX), exact via hi/lo split when operands are large. */
export function fxMul(a: number, b: number): number {
  const aa = Math.abs(a);
  const bb = Math.abs(b);
  if (aa < 3037000499 && bb < 3037000499 && aa * bb <= Number.MAX_SAFE_INTEGER) {
    return Math.trunc((a * b) / FX);
  }
  // hi/lo split matching the binary: hi=max, lo=min
  const hi = aa >= bb ? a : b;
  const lo = aa >= bb ? b : a;
  const q = Math.trunc(hi / FX);
  const r = hi - q * FX;
  return q * lo + Math.trunc((r * lo) / FX);
}

/** fixed-point divide: trunc(a*FX/b). */
export function fxDiv(a: number, b: number): number {
  if (b === 0) return 0;
  if (Math.abs(a) < 90000000000000) {
    return Math.trunc((a * FX) / b);
  }
  // large-numerator path: (a/b)*FX + fractional correction
  const q = Math.trunc(a / b);
  const rem = a - q * b;
  return q * FX + Math.trunc((rem * FX) / b);
}

export const fxMin = (a: number, b: number) => (a < b ? a : b);
export const fxMax = (a: number, b: number) => (a > b ? a : b);
