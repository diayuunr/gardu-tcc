'use client';

import CountUp from '@/components/CountUp';
import { useApiQuery } from '@/hooks/useApiQuery';
import type { ReportStats, RiskSummary } from '@/lib/api-types';
import { currentTimeBucket } from '@/lib/risk';

/**
 * Tiga angka ringkas di landing dari GET /reports/stats dan GET /risk/summary (bucket jam saat ini).
 * Sengaja TIDAK menampilkan "insiden terverifikasi" sebagai klaim besar: angkanya dapat memuat data simulasi.
 */
export default function LandingStats() {
  const bucket = currentTimeBucket();
  const stats = useApiQuery<ReportStats>('/reports/stats', {}, 'Statistik belum dapat dimuat.');
  const summary = useApiQuery<RiskSummary>('/risk/summary', { time_bucket: bucket }, 'Ringkasan belum dapat dimuat.');

  const regions = summary.data?.regions;
  const areas = regions ? regions.reduce((sum, region) => sum + region.cell_count, 0) + (summary.data?.unassigned_cell_count ?? 0) : null;

  const items: Array<{ label: string; value: number | null; loading: boolean; failed: boolean }> = [
    { label: 'Laporan total', value: stats.data?.total_reports ?? null, loading: stats.loading, failed: Boolean(stats.error) },
    { label: 'Area terpantau', value: regions ? regions.length : null, loading: summary.loading, failed: Boolean(summary.error) },
    { label: 'Prediksi Risiko', value: areas, loading: summary.loading, failed: Boolean(summary.error) },
  ];

  return (
    <div className="mt-12">
      <dl className="grid max-w-lg grid-cols-3 divide-x divide-line rounded-3xl border border-line bg-panel/50 backdrop-blur">
        {items.map((item) => (
          <div key={item.label} className="px-4 py-4 sm:px-5">
            <dd className="font-display text-2xl font-bold text-emerald-300">
              {item.value !== null ? (
                <CountUp value={item.value} />
              ) : item.loading ? (
                <span className="inline-block h-7 w-10 animate-pulse rounded bg-zinc-800 motion-reduce:animate-none" aria-label="Memuat" />
              ) : (
                <span aria-label="Tidak tersedia">-</span>
              )}
            </dd>
            <dt className="mt-1 text-[11px] leading-snug text-zinc-500">{item.label}</dt>
          </div>
        ))}
      </dl>

      <p className="mt-3 max-w-lg text-[11px] leading-relaxed text-zinc-600">
        Dari data tercatat, termasuk data simulasi untuk demonstrasi. Bukan statistik resmi kepolisian.
      </p>
    </div>
  );
}
