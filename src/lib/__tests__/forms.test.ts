import { describe, expect, it } from 'vitest';

import type { PickedPlace } from '@/lib/geo';
import { buildReportBody, hasReportErrors, mapServerFieldErrors, validateReport, type ReportFormValues } from '@/lib/report';
import {
  bucketOfInput,
  describeIncidentHours,
  hasErrors,
  nextWibOccurrence,
  requestKey,
  roadLabel,
  samePoint,
  validateRouteForm,
} from '@/lib/route';

const NOW = new Date('2026-10-20T15:00:00Z'); // 22.00 WIB

const place = (latitude: number, longitude: number): PickedPlace => ({ label: 'x', latitude, longitude }) as unknown as PickedPlace;

const baseReport: ReportFormValues = {
  description: 'Terjadi pengejaran sepeda motor di jalan raya.',
  kabkota: '3404',
  kecamatan: '340401',
  kelurahan: '',
  jalan: '',
  hint: '',
  timeMode: 'now',
  occurredAt: '',
};

describe('validateReport', () => {
  it('menerima isian minimal yang benar', () => {
    expect(hasReportErrors(validateReport(baseReport, NOW))).toBe(false);
  });

  it('menolak deskripsi pendek dan wilayah kosong', () => {
    const errors = validateReport({ ...baseReport, description: 'pendek', kabkota: '', kecamatan: '' }, NOW);

    expect(errors.description).toBeDefined();
    expect(errors.kabkota).toBeDefined();
    expect(errors.kecamatan).toBeDefined();
  });

  it('menolak email atau nomor telepon di kolom jalan (privasi)', () => {
    expect(validateReport({ ...baseReport, jalan: 'hubungi a@b.com' }, NOW).jalan).toBeDefined();
    expect(validateReport({ ...baseReport, jalan: '0812 3456 7890' }, NOW).jalan).toBeDefined();
    expect(validateReport({ ...baseReport, jalan: 'Jalan Kaliurang km 5' }, NOW).jalan).toBeUndefined();
  });

  it('menolak waktu kejadian di masa depan dan isian kosong', () => {
    expect(validateReport({ ...baseReport, timeMode: 'custom', occurredAt: '2026-10-21T10:00' }, NOW).occurredAt).toBeDefined();
    expect(validateReport({ ...baseReport, timeMode: 'custom', occurredAt: '' }, NOW).occurredAt).toBeDefined();
    expect(validateReport({ ...baseReport, timeMode: 'custom', occurredAt: '2026-10-20T20:00' }, NOW).occurredAt).toBeUndefined();
  });
});

describe('buildReportBody', () => {
  it('mengirim kode wilayah dan waktu berzona +07:00, tanpa field kosong', () => {
    const body = buildReportBody(baseReport, NOW) as unknown as Record<string, unknown>;

    expect(body.occurred_at).toBe('2026-10-20T22:00:00+07:00');
    expect(body.kabkota_kode).toBe('3404');
    expect(body.kecamatan_kode).toBe('340401');
    expect('jalan' in body).toBe(false);
    expect('kelurahan_kode' in body).toBe(false);
    expect('incident_type_hint' in body).toBe(false);
    expect('location_text' in body).toBe(false);
  });

  it('menyertakan jalan dan petunjuk jenis bila diisi', () => {
    const body = buildReportBody({ ...baseReport, jalan: ' Jl. Magelang ', hint: 'klitih' }, NOW) as unknown as Record<string, unknown>;

    expect(body.jalan).toBe('Jl. Magelang');
    expect(body.incident_type_hint).toBe('klitih');
  });
});

describe('mapServerFieldErrors', () => {
  it('memetakan field backend ke bidang formulir dan mengabaikan yang tak dikenal', () => {
    const mapped = mapServerFieldErrors([
      { field: 'kecamatan_kode', message: 'a' },
      { field: 'occurred_at', message: 'b' },
      { field: 'tidak_dikenal', message: 'c' },
    ] as never);

    expect(mapped).toEqual({ kecamatan: 'a', occurredAt: 'b' });
  });
});

describe('route form', () => {
  const a = place(-7.78, 110.37);
  const b = place(-7.6, 110.42);

  it('wajib asal dan tujuan, dan keduanya tidak boleh sama', () => {
    const empty = validateRouteForm({ origin: null, destination: null, departAt: null }, NOW);

    expect(empty.origin).toBeDefined();
    expect(empty.destination).toBeDefined();
    expect(validateRouteForm({ origin: a, destination: place(-7.78, 110.37), departAt: null }, NOW).form).toBeDefined();
    expect(hasErrors(validateRouteForm({ origin: a, destination: b, departAt: null }, NOW))).toBe(false);
    expect(samePoint(a, place(-7.78005, 110.37005))).toBe(true);
  });

  it('batas waktu berangkat: lebih dari 5 menit lalu dan lebih dari 30 hari ditolak', () => {
    const check = (departAt: string) => validateRouteForm({ origin: a, destination: b, departAt }, NOW).departAt;

    expect(check('2026-10-20T21:00')).toBeDefined();
    expect(check('2026-10-20T21:57')).toBeUndefined();
    expect(check('2026-10-20T23:00')).toBeUndefined();
    expect(check('2026-12-30T10:00')).toBeDefined();
    expect(check('')).toBeDefined();
  });

  it('bucketOfInput, requestKey, nextWibOccurrence', () => {
    expect(bucketOfInput('2026-10-20T02:00')).toBe('dini_hari');
    expect(bucketOfInput('2026-10-20T21:00')).toBe('malam');
    expect(bucketOfInput('rusak')).toBeNull();
    expect(requestKey({ origin: a, destination: b, departAt: null })).toContain('sekarang');
    // sekarang 22.00 WIB: 21.00 sudah lewat -> besok; 23.00 -> hari ini
    expect(nextWibOccurrence(21, NOW)).toBe('2026-10-21T21:00');
    expect(nextWibOccurrence(23, NOW)).toBe('2026-10-20T23:00');
  });

  it('roadLabel dan describeIncidentHours', () => {
    expect(roadLabel({ road_name: 'jalan tanpa nama' })).toBe('Jalan tanpa nama');
    expect(roadLabel({ road_name: null as unknown as string })).toBe('Jalan tanpa nama');
    expect(roadLabel({ road_name: 'Jalan Kaliurang' })).toBe('Jalan Kaliurang');
    expect(describeIncidentHours({ malam: 7, dini_hari: 2, pagi: 0 })).toBe('Malam 7 · Dini hari 2');
    expect(describeIncidentHours({})).toBe('');
  });
});
