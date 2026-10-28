import { describe, expect, it } from 'vitest';

import {
  formatClockWib,
  formatDistanceKm,
  formatDuration,
  formatExtraMinutes,
  formatMeters,
  formatPercent,
  formatScore,
  minutesFromNow,
  wibInputToIso,
  wibInputValue,
} from '@/lib/format';
import {
  currentTimeBucket,
  levelFromScore,
  normalizeLevel,
  routeStatusToUi,
  timeBucketOfHour,
  toUiLevel,
  wibHour,
} from '@/lib/risk';

describe('format', () => {
  it('meter, jarak, durasi, persen', () => {
    expect(formatMeters(250)).toBe('250 m');
    expect(formatMeters(1200)).toBe('1,2 km');
    expect(formatMeters(-1)).toBe('-');
    expect(formatDistanceKm(0.4)).toBe('400 m');
    expect(formatDuration(14)).toBe('14 menit');
    expect(formatDuration(65)).toBe('1 jam 5 menit');
    expect(formatDuration(120)).toBe('2 jam');
    expect(formatDuration(0.2)).toBe('kurang dari 1 menit');
    expect(formatExtraMinutes(0)).toBe('waktu tempuh sama');
    expect(formatExtraMinutes(6)).toBe('6 menit lebih lama');
    expect(formatExtraMinutes(-3)).toBe('3 menit lebih singkat');
    expect(formatPercent(0.634)).toBe('63%');
    expect(formatPercent(5)).toBe('100%');
    expect(formatScore(8.14)).toBe('8,1');
    expect(formatScore(Number.NaN)).toBe('-');
  });

  it('waktu selalu dibaca sebagai WIB (UTC+7), tidak bergantung zona mesin', () => {
    expect(formatClockWib('2026-10-20T15:00:00+00:00')).toBe('22.00 WIB');
    expect(wibInputValue(new Date('2026-10-20T17:30:00Z'))).toBe('2026-10-21T00:30');
    expect(wibInputToIso('2026-10-20T22:00')).toBe('2026-10-20T22:00:00+07:00');
    expect(wibInputToIso('bukan tanggal')).toBeNull();
    expect(wibInputToIso('2026-13-40T99:99')).toBeNull();
  });

  it('minutesFromNow: negatif untuk masa lalu, null untuk isian tak valid', () => {
    const now = new Date('2026-10-20T15:00:00Z'); // 22.00 WIB
    expect(minutesFromNow('2026-10-20T22:30', now)).toBe(30);
    expect(minutesFromNow('2026-10-20T21:00', now)).toBe(-60);
    expect(minutesFromNow('', now)).toBeNull();
  });
});

describe('risk', () => {
  it('ambang skor sama dengan backend (sedang >= 3, tinggi >= 7)', () => {
    expect(levelFromScore(2.99)).toBe('rendah');
    expect(levelFromScore(3)).toBe('sedang');
    expect(levelFromScore(6.99)).toBe('sedang');
    expect(levelFromScore(7)).toBe('tinggi');
  });

  it('kosakata level dipetakan konsisten', () => {
    expect(toUiLevel('rendah')).toBe('aman');
    expect(toUiLevel('sedang')).toBe('waspada');
    expect(toUiLevel('tinggi')).toBe('rawan');
    expect(routeStatusToUi('berisiko_tinggi')).toBe('rawan');
    expect(routeStatusToUi('waspada')).toBe('waspada');
    expect(normalizeLevel('rendah')).toBe('aman');
    expect(normalizeLevel('berisiko_tinggi')).toBe('rawan');
  });

  it('bucket jam WIB: dini_hari 0-5, pagi 5-11, siang 11-15, sore 15-18, malam 18-24', () => {
    const expected: Array<[number, string]> = [
      [0, 'dini_hari'],
      [4, 'dini_hari'],
      [5, 'pagi'],
      [10, 'pagi'],
      [11, 'siang'],
      [14, 'siang'],
      [15, 'sore'],
      [17, 'sore'],
      [18, 'malam'],
      [23, 'malam'],
    ];

    for (const [hour, bucket] of expected) expect(timeBucketOfHour(hour)).toBe(bucket);
  });

  it('bucket saat ini memakai WIB, bukan zona mesin', () => {
    // 20.00 UTC = 03.00 WIB hari berikutnya -> dini hari
    expect(wibHour(new Date('2026-10-20T20:00:00Z'))).toBe(3);
    expect(currentTimeBucket(new Date('2026-10-20T20:00:00Z'))).toBe('dini_hari');
    expect(currentTimeBucket(new Date('2026-10-20T14:00:00Z'))).toBe('malam'); // 21.00 WIB
  });
});
