import { describe, expect, it } from 'vitest';

import { ApiError, buildUrl, classifyStatus, errorMessage, messageFor } from '@/lib/api';
import { DECISIONS, decisionMessage, decisionsFor, filterToStatus, previewText } from '@/lib/moderation';
import { flagReasonLabel } from '@/lib/report-status';
import { countByLevel, sortCells, totalIncidents, uniqueRegions } from '@/lib/riskmap';

describe('api', () => {
  it('klasifikasi status HTTP', () => {
    expect(classifyStatus(401)).toBe('unauthorized');
    expect(classifyStatus(403)).toBe('forbidden');
    expect(classifyStatus(404)).toBe('not_found');
    expect(classifyStatus(422)).toBe('validation');
    expect(classifyStatus(429)).toBe('rate_limit');
    expect(classifyStatus(503)).toBe('unavailable');
    expect(classifyStatus(502)).toBe('server');
  });

  it('pesan: detail backend dipakai, kecuali jaringan/timeout', () => {
    expect(messageFor('validation', ' Deskripsi terlalu pendek ')).toBe('Deskripsi terlalu pendek');
    expect(messageFor('server', { x: 1 })).toMatch(/kesalahan/i);
    expect(messageFor('network', 'detail diabaikan')).toMatch(/terhubung/i);
    expect(errorMessage(new ApiError('forbidden', 'Akses ditolak.'))).toBe('Akses ditolak.');
    expect(errorMessage(new Error('rahasia internal'), 'cadangan')).toBe('cadangan');
  });

  it('buildUrl membuang parameter kosong dan meng-encode nilai', () => {
    const url = buildUrl('/areas', { level: 'kecamatan', parent: undefined, q: '', n: 0, s: 'a b' });

    expect(url.endsWith('/areas?level=kecamatan&n=0&s=a+b')).toBe(true);
    expect(buildUrl('/x').endsWith('/x')).toBe(true);
  });
});

describe('moderation', () => {
  it('filter bawaan tanpa parameter status', () => {
    expect(filterToStatus('tinjau')).toBeUndefined();
    expect(filterToStatus('ditandai_hoaks')).toBe('ditandai_hoaks');
  });

  it('pilihan keputusan = semua kecuali yang sudah berlaku', () => {
    expect(decisionsFor('menunggu_verifikasi')).toEqual(['terverifikasi', 'ditandai_hoaks']);
    expect(decisionsFor('terverifikasi')).toEqual(['ditandai_hoaks', 'menunggu_verifikasi']);
    expect(decisionsFor('ditandai_duplikat')).toHaveLength(3);
  });

  it('pesan hasil jujur untuk changed=false dan penjadwalan ulang skor', () => {
    const base = { id: 'x', status: 'terverifikasi', incident_status: null } as const;

    expect(decisionMessage('GRD-1', 'terverifikasi', { ...base, changed: false, scores_refresh_scheduled: false })).toMatch(
      /tidak ada perubahan/,
    );

    const ok = decisionMessage('GRD-1', 'ditandai_hoaks', { ...base, changed: true, scores_refresh_scheduled: true });

    expect(ok).toContain(DECISIONS.ditandai_hoaks.done);
    expect(ok).toMatch(/dihitung ulang/);
  });

  it('previewText memotong teks panjang di batas kata', () => {
    expect(previewText('pendek')).toEqual({ text: 'pendek', truncated: false });

    const long = previewText('kata '.repeat(100), 50);

    expect(long.truncated).toBe(true);
    expect(long.text.length).toBeLessThanOrEqual(51);
    expect(long.text.endsWith('…')).toBe(true);
  });

  it('alasan penandaan: dikenal, tak dikenal, kosong', () => {
    expect(flagReasonLabel('kata_berulang')).toMatch(/diulang/);
    expect(flagReasonLabel('kode_baru')).toBe('Ditandai sistem');
    expect(flagReasonLabel(null)).toBeNull();
  });
});

describe('riskmap', () => {
  const cell = (label: string, risk_score: number, count: number) =>
    ({ label, risk_score, contributing_incident_count: count, place_name: label }) as never;

  it('urut skor, lalu jumlah kejadian, lalu nama; total kejadian', () => {
    const sorted = sortCells([cell('B', 5, 1), cell('A', 5, 3), cell('C', 9, 0)]) as unknown as Array<{ label: string }>;

    expect(sorted.map((c) => c.label)).toEqual(['C', 'A', 'B']);
    expect(totalIncidents([cell('A', 1, 3), cell('B', 1, 2)])).toBe(5);
  });

  it('uniqueRegions membuang kode kembar dan membedakan label kembar', () => {
    const region = (kode: string, label: string) =>
      ({ kecamatan_kode: kode, label, place_name: label, risk_level: 'sedang' }) as never;
    const result = uniqueRegions([region('1', 'Kec. A'), region('1', 'Kec. A'), region('2', 'Kec. B'), region('3', 'Kec. B')]);

    expect(result.map((r) => r.displayLabel)).toEqual(['Kec. A', 'Kec. B (2)', 'Kec. B (3)']);
  });

  it('countByLevel', () => {
    expect(countByLevel([{ risk_level: 'tinggi' }, { risk_level: 'rendah' }, { risk_level: 'tinggi' }])).toEqual({
      rendah: 1,
      sedang: 0,
      tinggi: 2,
    });
  });
});
