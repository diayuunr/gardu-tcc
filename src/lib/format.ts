/**
 * Helper format tampilan (bahasa Indonesia, WIB). Fungsi murni tanpa efek samping, aman diuji unit.
 * Waktu selalu ditampilkan di WIB (Asia/Jakarta) agar sama dengan bucket jam backend, apa pun zona waktu peramban.
 */

const WIB_TIME_ZONE = 'Asia/Jakarta';
const WIB_OFFSET_MS = 7 * 60 * 60 * 1000;

function numberFormat(maxFractionDigits: number, minFractionDigits = 0): Intl.NumberFormat {
  return new Intl.NumberFormat('id-ID', {
    maximumFractionDigits: maxFractionDigits,
    minimumFractionDigits: minFractionDigits,
  });
}

export function formatNumber(value: number, maxFractionDigits = 0): string {
  if (!Number.isFinite(value)) return '-';

  return numberFormat(maxFractionDigits).format(value);
}

/** Skor 0-10 dengan satu desimal, mis. "8,1". */
export function formatScore(score: number): string {
  if (!Number.isFinite(score)) return '-';

  return numberFormat(1, 1).format(score);
}

/** Meter -> "250 m" atau "1,2 km". */
export function formatMeters(meters: number): string {
  if (!Number.isFinite(meters) || meters < 0) return '-';

  if (meters < 1000) return `${Math.round(meters)} m`;

  return `${numberFormat(1).format(meters / 1000)} km`;
}

/** Kilometer -> "7,5 km" (di bawah 1 km ditulis dalam meter). */
export function formatDistanceKm(km: number): string {
  if (!Number.isFinite(km) || km < 0) return '-';

  return formatMeters(km * 1000);
}

/** Menit -> "14 menit", "1 jam 5 menit", "2 jam". */
export function formatDuration(minutes: number): string {
  if (!Number.isFinite(minutes) || minutes < 0) return '-';

  const total = Math.round(minutes);

  if (total < 1) return 'kurang dari 1 menit';
  if (total < 60) return `${total} menit`;

  const hours = Math.floor(total / 60);
  const rest = total % 60;

  return rest === 0 ? `${hours} jam` : `${hours} jam ${rest} menit`;
}

/** Selisih waktu vs rute utama (negatif = lebih cepat). */
export function formatExtraMinutes(extra: number): string {
  const value = Math.round(extra);

  if (value === 0) return 'waktu tempuh sama';
  if (value > 0) return `${value} menit lebih lama`;

  return `${-value} menit lebih singkat`;
}

/** 0-1 -> "63%". */
export function formatPercent(fraction: number): string {
  if (!Number.isFinite(fraction)) return '-';

  return `${Math.round(Math.min(1, Math.max(0, fraction)) * 100)}%`;
}

/** "3 kejadian", "1 kejadian", "0 kejadian". */
export function formatCount(value: number, noun: string): string {
  return `${formatNumber(value)} ${noun}`;
}

function wibParts(date: Date, options: Intl.DateTimeFormatOptions): Record<string, string> {
  const parts = new Intl.DateTimeFormat('id-ID', {
    timeZone: WIB_TIME_ZONE,
    ...options,
  }).formatToParts(date);

  return Object.fromEntries(parts.map((part) => [part.type, part.value]));
}

function toDate(value: string | Date): Date | null {
  const date = value instanceof Date ? value : new Date(value);

  return Number.isNaN(date.getTime()) ? null : date;
}

/** "22.00 WIB" */
export function formatClockWib(value: string | Date): string {
  const date = toDate(value);

  if (!date) return '-';

  const { hour, minute } = wibParts(date, {
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  });

  return `${hour}.${minute} WIB`;
}

/** "28 Okt 2026" */
export function formatDateWib(value: string | Date): string {
  const date = toDate(value);

  if (!date) return '-';

  const { day, month, year } = wibParts(date, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  });

  return `${day} ${month} ${year}`;
}

/** "28 Okt 2026, 22.00 WIB" */
export function formatDateTimeWib(value: string | Date): string {
  const date = toDate(value);

  if (!date) return '-';

  return `${formatDateWib(date)}, ${formatClockWib(date)}`;
}

// ---------------------------------------------------------------------------
// Isian <input type="datetime-local"> yang selalu dibaca sebagai waktu dinding WIB.
// ---------------------------------------------------------------------------

/** Nilai `datetime-local` (YYYY-MM-DDTHH:mm) untuk waktu dinding WIB pada saat `date`. */
export function wibInputValue(date: Date = new Date()): string {
  return new Date(date.getTime() + WIB_OFFSET_MS).toISOString().slice(0, 16);
}

const INPUT_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/;

/** Isian waktu WIB -> ISO 8601 dengan zona (`...+07:00`); null bila formatnya tidak valid. */
export function wibInputToIso(value: string): string | null {
  if (!INPUT_PATTERN.test(value)) return null;

  const iso = `${value}:00+07:00`;

  return Number.isNaN(new Date(iso).getTime()) ? null : iso;
}

/** Selisih menit (isian WIB - sekarang); negatif = di masa lalu. Null bila isian tidak valid. */
export function minutesFromNow(value: string, now: Date = new Date()): number | null {
  const iso = wibInputToIso(value);

  if (!iso) return null;

  return Math.round((new Date(iso).getTime() - now.getTime()) / 60_000);
}
