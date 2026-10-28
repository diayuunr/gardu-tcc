'use client';

import dynamic from 'next/dynamic';
import { useMemo, useState } from 'react';
import { RefreshCw } from 'react-feather';

import LevelLegend from '@/components/LevelLegend';
import type { RiskMapStatus } from '@/components/risk/RiskHeatMap';
import RiskBadge from '@/components/RiskBadge';
import { useRiskData } from '@/hooks/useRiskData';
import { formatCount, formatDateTimeWib, formatNumber, formatScore } from '@/lib/format';
import { TIME_BUCKETS, TIME_BUCKET_INFO, TimeBucket, currentTimeBucket } from '@/lib/risk';
import { countByLevel, sortCells, totalIncidents, uniqueRegions } from '@/lib/riskmap';

const RiskHeatMap = dynamic(() => import('@/components/risk/RiskHeatMap'), {
  ssr: false,
  loading: () => (
    <div className="flex h-full w-full items-center justify-center rounded-3xl border border-line bg-ink" role="status">
      <span className="h-6 w-6 animate-spin rounded-full border-2 border-emerald-400/30 border-t-emerald-400 motion-reduce:animate-none" />
      <span className="sr-only">Memuat peta</span>
    </div>
  ),
});

const REGIONS_PREVIEW = 8;
const TABLE_PREVIEW = 15;

/** Peta kerawanan: pilih periode jam, lihat heatmap, dan daftar skor tertinggi per kecamatan. */
export default function RiskExplorer() {
  const [bucket, setBucket] = useState<TimeBucket>(() => currentTimeBucket());
  const [highlight, setHighlight] = useState<string | null>(null);
  const [showAllRegions, setShowAllRegions] = useState(false);
  const [showAllCells, setShowAllCells] = useState(false);
  const [view, setView] = useState<'peta' | 'tabel'>('peta');
  const [mapStatus, setMapStatus] = useState<RiskMapStatus>('loading');

  const { data, loading, error, retry } = useRiskData(bucket);

  const cells = useMemo(() => data?.heatmap.cells ?? [], [data]);
  const regions = useMemo(() => uniqueRegions(data?.summary?.regions ?? []), [data]);
  const sortedCells = useMemo(() => sortCells(cells), [cells]);
  const levels = useMemo(() => countByLevel(regions), [regions]);

  const info = TIME_BUCKET_INFO[bucket];
  const mapBroken = mapStatus === 'no-token' || mapStatus === 'failed';
  const showTable = view === 'tabel' || mapBroken;
  const empty = !loading && !error && cells.length === 0;
  const shownRegions = showAllRegions ? regions : regions.slice(0, REGIONS_PREVIEW);
  const shownCells = showAllCells ? sortedCells : sortedCells.slice(0, TABLE_PREVIEW);
  const updatedAt = data?.heatmap.updated_at ?? null;

  function chooseBucket(next: TimeBucket) {
    setBucket(next);
    setHighlight(null);
    setShowAllRegions(false);
    setShowAllCells(false);
  }

  return (
    <div className="space-y-6">
      <div>
        <p className="mb-2 text-xs font-semibold uppercase tracking-[0.2em] text-zinc-500">Periode jam (WIB)</p>

        <div className="flex flex-wrap gap-2" role="group" aria-label="Pilih periode jam">
          {TIME_BUCKETS.map((value) => (
            <button
              key={value}
              type="button"
              aria-pressed={bucket === value}
              onClick={() => chooseBucket(value)}
              className={`rounded-2xl border px-4 py-2 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400/60 ${
                bucket === value
                  ? 'border-emerald-400/60 bg-emerald-400/10 text-emerald-200'
                  : 'border-line text-zinc-400 hover:border-emerald-400/30 hover:text-zinc-200'
              }`}
            >
              <span className="block text-sm font-semibold">{TIME_BUCKET_INFO[value].label}</span>
              <span className="block text-[11px] opacity-70">{TIME_BUCKET_INFO[value].range}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div className="min-w-0 space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-zinc-400" aria-live="polite">
              {loading
                ? 'Memuat data...'
                : error
                  ? ''
                  : `${formatCount(cells.length, 'area')} · periode ${info.label.toLowerCase()}${
                      updatedAt ? ` · diperbarui ${formatDateTimeWib(updatedAt)}` : ''
                    }`}
            </p>

            {!mapBroken && (
              <div className="inline-flex rounded-full border border-line p-1" role="group" aria-label="Pilih tampilan">
                {(
                  [
                    ['peta', 'Peta'],
                    ['tabel', 'Tabel'],
                  ] as const
                ).map(([value, text]) => (
                  <button
                    key={value}
                    type="button"
                    aria-pressed={view === value}
                    onClick={() => setView(value)}
                    className={`rounded-full px-4 py-1 text-xs font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400/60 ${
                      view === value ? 'bg-emerald-400 text-emerald-950' : 'text-zinc-400 hover:text-zinc-200'
                    }`}
                  >
                    {text}
                  </button>
                ))}
              </div>
            )}
          </div>

          {error && (
            <div className="rounded-3xl border border-red-400/30 bg-red-400/5 p-5" role="alert">
              <p className="font-display text-lg font-semibold text-red-200">Data kerawanan belum dapat dimuat</p>
              <p className="mt-2 text-sm text-zinc-200">{error}</p>
              <button type="button" onClick={retry} className="btn-ghost mt-4 !px-5 !py-2">
                <RefreshCw size={14} aria-hidden="true" />
                Coba lagi
              </button>
            </div>
          )}

          {/* Wadah peta: TINGGI EKSPLISIT (mapbox-gl.css menimpa absolute inset-0). */}
          {!error && (view === 'peta' || mapBroken) && (
            <div className={mapBroken ? 'h-[240px]' : 'h-[58vh] min-h-[340px] lg:h-[620px]'}>
              <RiskHeatMap
                cells={cells}
                bucketLabel={`${info.label} (${info.range} WIB)`}
                highlightPlace={highlight}
                onStatusChange={setMapStatus}
                className="h-full w-full"
              />
            </div>
          )}

          {empty && (
            <p className="rounded-2xl border border-amber-400/30 bg-amber-400/10 px-4 py-3 text-sm leading-relaxed text-amber-100" role="status">
              Belum ada data kerawanan pada periode {info.label.toLowerCase()}. Ini <strong>bukan berarti aman</strong>,
              hanya belum ada kejadian tercatat yang cukup untuk dinilai.
            </p>
          )}

          {!error && showTable && !empty && (
            <div className="glass-card overflow-hidden p-0">
              <div className="overflow-x-auto">
                <table className="w-full min-w-[420px] text-left text-sm">
                  <caption className="px-4 pb-2 pt-4 text-left text-xs font-semibold uppercase tracking-[0.2em] text-zinc-500">
                    Area dengan skor tertinggi · {info.label.toLowerCase()}
                  </caption>
                  <thead>
                    <tr className="border-b border-line text-xs text-zinc-500">
                      <th scope="col" className="px-4 py-2 font-medium">Area</th>
                      <th scope="col" className="px-4 py-2 font-medium">Tingkat</th>
                      <th scope="col" className="px-4 py-2 text-right font-medium">Skor</th>
                      <th scope="col" className="px-4 py-2 text-right font-medium">Kejadian tercatat</th>
                    </tr>
                  </thead>
                  <tbody>
                    {shownCells.map((cell) => (
                      <tr key={`${cell.area_name}`} className="border-b border-line/60 last:border-0">
                        <th scope="row" className="px-4 py-2 font-medium text-zinc-200">{cell.label}</th>
                        <td className="px-4 py-2"><RiskBadge level={cell.risk_level} size="sm" /></td>
                        <td className="px-4 py-2 text-right text-zinc-300">{formatScore(cell.risk_score)}</td>
                        <td className="px-4 py-2 text-right text-zinc-400">{formatNumber(cell.contributing_incident_count)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {sortedCells.length > TABLE_PREVIEW && (
                <button
                  type="button"
                  onClick={() => setShowAllCells((value) => !value)}
                  className="w-full border-t border-line px-4 py-3 text-xs font-semibold text-emerald-300 hover:bg-white/5"
                >
                  {showAllCells ? 'Ringkas tabel' : `Tampilkan semua ${sortedCells.length} area`}
                </button>
              )}
            </div>
          )}

          <LevelLegend variant="bar" />
        </div>

        <aside className="space-y-4" aria-label="Ringkasan per kecamatan">
          <div className="glass-card grid grid-cols-3 divide-x divide-line p-0 text-center">
            {(
              [
                ['Kec. tinggi', levels.tinggi, 'text-red-300'],
                ['Kec. sedang', levels.sedang, 'text-amber-300'],
                ['Kec. rendah', levels.rendah, 'text-emerald-300'],
              ] as const
            ).map(([label, value, color]) => (
              <div key={label} className="px-3 py-4">
                <p className={`font-display text-2xl font-bold ${color}`}>{loading ? '-' : value}</p>
                <p className="mt-1 text-[11px] text-zinc-500">{label}</p>
              </div>
            ))}
          </div>

          <div className="glass-card p-5">
            <h2 className="text-xs font-semibold uppercase tracking-[0.2em] text-zinc-500">Skor tertinggi per kecamatan</h2>

            {loading && (
              <ul className="mt-4 space-y-3" aria-hidden="true">
                {[0, 1, 2, 3].map((n) => (
                  <li key={n} className="h-12 animate-pulse rounded-xl bg-white/5 motion-reduce:animate-none" />
                ))}
              </ul>
            )}

            {!loading && data?.summaryError && (
              <p className="mt-3 text-sm text-amber-300" role="alert">{data.summaryError}</p>
            )}

            {!loading && !error && !data?.summaryError && regions.length === 0 && (
              <p className="mt-3 text-sm leading-relaxed text-zinc-500">
                Belum ada kecamatan berskor pada periode ini. Ini bukan berarti aman.
              </p>
            )}

            {!loading && regions.length > 0 && (
              <>
                <ol className="mt-3 space-y-2">
                  {shownRegions.map((region, index) => {
                    const active = highlight === region.place_name;

                    return (
                      <li key={region.kecamatan_kode}>
                        <button
                          type="button"
                          aria-pressed={active}
                          onClick={() => {
                            setHighlight(active ? null : region.place_name);
                            setView('peta');
                          }}
                          className={`flex w-full items-center gap-3 rounded-xl border p-3 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400/60 ${
                            active ? 'border-emerald-400/50 bg-emerald-400/10' : 'border-line hover:border-emerald-400/30'
                          }`}
                        >
                          <span className="w-5 shrink-0 text-center text-xs font-semibold text-zinc-500">{index + 1}</span>
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-sm font-medium text-zinc-100">{region.displayLabel}</span>
                            <span className="block text-xs text-zinc-500">
                              {formatCount(region.cell_count, 'area')} · {formatCount(region.incident_count, 'kejadian tercatat')}
                            </span>
                          </span>
                          <RiskBadge level={region.risk_level} score={region.risk_score} size="sm" />
                        </button>
                      </li>
                    );
                  })}
                </ol>

                {regions.length > REGIONS_PREVIEW && (
                  <button
                    type="button"
                    onClick={() => setShowAllRegions((value) => !value)}
                    className="mt-3 text-xs font-semibold text-emerald-300 underline-offset-2 hover:underline"
                  >
                    {showAllRegions ? 'Ringkas daftar' : `Tampilkan semua ${regions.length} kecamatan`}
                  </button>
                )}
              </>
            )}
          </div>

          {!loading && !error && cells.length > 0 && (
            <p className="px-1 text-xs leading-relaxed text-zinc-500">
              Total {formatCount(totalIncidents(cells), 'kejadian tercatat')} berkontribusi pada periode ini
              (satu kejadian dapat memengaruhi area di sekitarnya). Skor menggambarkan riwayat kejadian tercatat, bukan
              prediksi pasti dan bukan jaminan keamanan.
            </p>
          )}
        </aside>
      </div>
    </div>
  );
}
