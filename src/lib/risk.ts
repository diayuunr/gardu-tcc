/**
 * Satu-satunya tempat pemetaan level risiko backend -> tampilan (nama, warna) dan bucket jam.
 * Ambang mengikuti backend/docs/API.md: skor 0-10, sedang >= 3, tinggi >= 7.
 */

/** Level dari backend untuk sel/ruas: rendah | sedang | tinggi. */
export type BackendRiskLevel = 'rendah' | 'sedang' | 'tinggi';

/** Level untuk tampilan (nama lama dipertahankan agar komponen yang ada tetap kompatibel). */
export type RiskLevel = 'aman' | 'waspada' | 'rawan';

/** Status keseluruhan rute dari POST /route/check. */
export type RouteStatus = 'aman' | 'waspada' | 'berisiko_tinggi';

export const RISK_THRESHOLDS = { sedang: 3, tinggi: 7 } as const;
export const MAX_RISK_SCORE = 10;

/** Warna garis/penanda peta per level backend (sama dengan contoh di API.md). */
export const LEVEL_HEX: Record<BackendRiskLevel, string> = {
  rendah: '#34d399',
  sedang: '#fbbf24',
  tinggi: '#f87171',
};

export const LEVEL_STYLE: Record<
  RiskLevel,
  { label: string; text: string; bg: string; ring: string; hex: string }
> = {
  aman: {
    label: 'Aman',
    text: 'text-emerald-300',
    bg: 'bg-emerald-400/10',
    ring: 'ring-emerald-400/30',
    hex: LEVEL_HEX.rendah,
  },
  waspada: {
    label: 'Waspada',
    text: 'text-amber-300',
    bg: 'bg-amber-400/10',
    ring: 'ring-amber-400/30',
    hex: LEVEL_HEX.sedang,
  },
  rawan: {
    label: 'Rawan',
    text: 'text-red-300',
    bg: 'bg-red-400/10',
    ring: 'ring-red-400/30',
    hex: LEVEL_HEX.tinggi,
  },
};

export function toUiLevel(level: BackendRiskLevel): RiskLevel {
  if (level === 'tinggi') return 'rawan';
  if (level === 'sedang') return 'waspada';
  return 'aman';
}

export function routeStatusToUi(status: RouteStatus): RiskLevel {
  if (status === 'berisiko_tinggi') return 'rawan';
  return status;
}

/** Level dari skor 0-10 dengan ambang backend (untuk legenda dan skor yang hanya berupa angka). */
export function levelFromScore(score: number): BackendRiskLevel {
  if (score >= RISK_THRESHOLDS.tinggi) return 'tinggi';
  if (score >= RISK_THRESHOLDS.sedang) return 'sedang';
  return 'rendah';
}

/** Semua kosakata level yang dikenal UI: level sel/ruas backend, level tampilan, dan status rute. */
export type AnyLevel = BackendRiskLevel | RiskLevel | RouteStatus;

/** Samakan kosakata level apa pun ke level tampilan (aman | waspada | rawan). */
export function normalizeLevel(level: AnyLevel): RiskLevel {
  if (level === 'rendah' || level === 'aman') return 'aman';
  if (level === 'sedang' || level === 'waspada') return 'waspada';

  return 'rawan';
}

/** Rentang skor tiap level (untuk legenda), dari ambang backend. */
export const LEVEL_RANGES: ReadonlyArray<{
  level: BackendRiskLevel;
  title: string;
  range: string;
}> = [
  { level: 'rendah', title: 'Rendah', range: `0 - ${(RISK_THRESHOLDS.sedang - 0.1).toFixed(1).replace('.', ',')}` },
  {
    level: 'sedang',
    title: 'Sedang',
    range: `${RISK_THRESHOLDS.sedang} - ${(RISK_THRESHOLDS.tinggi - 0.1).toFixed(1).replace('.', ',')}`,
  },
  { level: 'tinggi', title: 'Tinggi', range: `${RISK_THRESHOLDS.tinggi} - ${MAX_RISK_SCORE}` },
];

export const ROUTE_STATUS_LABEL: Record<RouteStatus, string> = {
  aman: 'Relatif aman',
  waspada: 'Perlu waspada',
  berisiko_tinggi: 'Risiko tinggi',
};

// ---------------------------------------------------------------------------
// Bucket jam (WIB). Batas sama dengan TIME_BUCKET_HOURS di backend.
// ---------------------------------------------------------------------------

export type TimeBucket = 'dini_hari' | 'pagi' | 'siang' | 'sore' | 'malam';

export const TIME_BUCKETS: readonly TimeBucket[] = [
  'dini_hari',
  'pagi',
  'siang',
  'sore',
  'malam',
];

export const TIME_BUCKET_INFO: Record<
  TimeBucket,
  { label: string; range: string; startHour: number; endHour: number }
> = {
  dini_hari: { label: 'Dini hari', range: '00.00-05.00', startHour: 0, endHour: 5 },
  pagi: { label: 'Pagi', range: '05.00-11.00', startHour: 5, endHour: 11 },
  siang: { label: 'Siang', range: '11.00-15.00', startHour: 11, endHour: 15 },
  sore: { label: 'Sore', range: '15.00-18.00', startHour: 15, endHour: 18 },
  malam: { label: 'Malam', range: '18.00-24.00', startHour: 18, endHour: 24 },
};

const WIB_OFFSET_HOURS = 7;

/** Jam (0-23) di WIB untuk sebuah waktu, tidak bergantung zona waktu peramban. */
export function wibHour(date: Date = new Date()): number {
  return (date.getUTCHours() + WIB_OFFSET_HOURS) % 24;
}

export function timeBucketOfHour(hour: number): TimeBucket {
  const found = TIME_BUCKETS.find((bucket) => {
    const { startHour, endHour } = TIME_BUCKET_INFO[bucket];
    return hour >= startHour && hour < endHour;
  });

  return found ?? 'malam';
}

export function currentTimeBucket(date: Date = new Date()): TimeBucket {
  return timeBucketOfHour(wibHour(date));
}

export function formatTimeBucket(value: string): string {
  if (value in TIME_BUCKET_INFO) {
    return TIME_BUCKET_INFO[value as TimeBucket].label;
  }

  return value.replaceAll('_', ' ');
}
