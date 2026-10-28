import type { RiskLevel } from '@/lib/types';

export const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000';

// Level dari backend (rendah/sedang/tinggi) -> level yang dipakai UI.
export type BackendRiskLevel = 'rendah' | 'sedang' | 'tinggi';

export type TimeBucket = 'dini_hari' | 'pagi' | 'siang' | 'sore' | 'malam';

export const TIME_BUCKETS: TimeBucket[] = [
  'dini_hari',
  'pagi',
  'siang',
  'sore',
  'malam',
];

export function toUiLevel(level: BackendRiskLevel): RiskLevel {
  if (level === 'tinggi') return 'rawan';
  if (level === 'sedang') return 'waspada';
  return 'aman';
}

// Bucket jam sesuai backend (WIB), dihitung dari jam lokal peramban.
export function currentTimeBucket(): TimeBucket {
  const hour = new Date().getHours();

  if (hour < 5) return 'dini_hari';
  if (hour < 11) return 'pagi';
  if (hour < 15) return 'siang';
  if (hour < 18) return 'sore';
  return 'malam';
}

export function formatTimeBucket(value: string): string {
  return value
    .replaceAll('_', ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

// FastAPI: `detail` berupa string (HTTPException) atau array (422 validasi).
export async function readErrorDetail(
  response: Response,
  fallback: string,
): Promise<string> {
  try {
    const body = await response.json();

    if (typeof body?.detail === 'string') {
      return body.detail;
    }
  } catch {
    // respons bukan JSON
  }

  if (response.status === 429) {
    return 'Terlalu banyak permintaan, coba lagi sebentar lagi.';
  }

  return fallback;
}
