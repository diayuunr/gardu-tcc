'use client';

import { forwardRef, useState } from 'react';
import { AlertTriangle, Info, Map as MapIcon } from 'react-feather';

import RiskBadge from '@/components/RiskBadge';
import type { RouteCheck } from '@/lib/api-types';
import {
  formatDateTimeWib,
  formatDistanceKm,
  formatDuration,
  formatExtraMinutes,
  formatMeters,
  formatPercent,
  formatScore,
} from '@/lib/format';
import { LEVEL_HEX, ROUTE_STATUS_LABEL, RouteStatus, TIME_BUCKET_INFO, formatTimeBucket } from '@/lib/risk';
import { LEVEL_TITLE, RouteView, categoryLabel, roadLabel } from '@/lib/route';

const STATUS_COPY: Record<RouteStatus, string> = {
  aman: 'Belum ditemukan bagian jalur yang berisiko pada data kejadian yang tercatat.',
  waspada: 'Sebagian jalur melewati area dengan riwayat kejadian tercatat pada jam ini.',
  berisiko_tinggi: 'Jalur melewati area dengan riwayat kejadian tercatat yang cukup banyak pada jam ini.',
};

const GENERAL_TIPS = [
  'Pertimbangkan jam keberangkatan lain atau rute alternatif bila tersedia.',
  'Bila memungkinkan, bepergian bersama dan beri tahu orang terdekat tentang rute Anda.',
  'Hindari berhenti lama di ruas yang sepi.',
];

const SEGMENTS_PREVIEW = 8;

/**
 * Panel hasil Cek Rute: pilihan rute, status + alasan (dari backend, apa adanya), catatan data, daftar ruas jalan, dan
 * keterangan "bukan jaminan keamanan". Nada netral; tidak ada koordinat/deskripsi insiden individual.
 */
const RouteResultPanel = forwardRef<
  HTMLHeadingElement,
  {
    data: RouteCheck;
    views: RouteView[];
    selectedIndex: number;
    onSelectRoute: (index: number) => void;
    focusedSegment: number | null;
    onFocusSegment: (segmentIndex: number | null) => void;
    stale: boolean;
    /** Label pilihan pengguna saat memeriksa (bukan nama dari backend). */
    originLabel: string;
    destinationLabel: string;
    onShowMap: () => void;
    mapAvailable: boolean;
  }
>(function RouteResultPanel(
  {
    data,
    views,
    selectedIndex,
    onSelectRoute,
    focusedSegment,
    onFocusSegment,
    stale,
    originLabel,
    destinationLabel,
    onShowMap,
    mapAvailable,
  },
  headingRef,
) {
  const [showAllSegments, setShowAllSegments] = useState(false);

  const selected = views.find((view) => view.index === selectedIndex) ?? views[0];
  const recommended = data.recommended_route;
  const departBuckets = selected.timeBuckets.map(formatTimeBucket).join(', ');
  const shownSegments = showAllSegments ? selected.segments : selected.segments.slice(0, SEGMENTS_PREVIEW);
  const hiddenSegments = selected.segments.length - shownSegments.length;
  const notes = [data.data_note, ...data.location_notes].filter((note): note is string => Boolean(note));

  return (
    <section className="glass-card space-y-6 p-5 sm:p-6" aria-labelledby="hasil-rute-judul">
      <header>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-emerald-400">Hasil pemeriksaan rute</p>

            <h2
              id="hasil-rute-judul"
              ref={headingRef}
              tabIndex={-1}
              className="mt-1.5 break-words font-display text-xl font-bold text-white outline-none"
            >
              {originLabel} <span aria-hidden="true">→</span>
              <span className="sr-only"> menuju </span> {destinationLabel}
            </h2>
          </div>

          {mapAvailable && (
            <button type="button" onClick={onShowMap} className="btn-ghost shrink-0 !px-3 !py-1.5 text-xs lg:hidden">
              <MapIcon size={13} aria-hidden="true" />
              Lihat peta
            </button>
          )}
        </div>

        <p className="mt-2 text-xs leading-relaxed text-zinc-500">
          Wilayah: {data.origin.place_name} <span aria-hidden="true">→</span>
          <span className="sr-only"> menuju </span> {data.destination.place_name}
        </p>

        <p className="mt-1 text-xs text-zinc-500">
          Berangkat {formatDateTimeWib(data.departure_time)}
          {departBuckets && ` · jam ${departBuckets.toLowerCase()}`}
        </p>
      </header>

      {stale && (
        <p role="status" className="rounded-2xl border border-amber-400/30 bg-amber-400/10 px-4 py-3 text-xs leading-relaxed text-amber-200">
          Titik atau waktu berubah sejak pemeriksaan ini. Tekan &quot;Periksa Risiko Rute&quot; lagi untuk memperbarui hasil.
        </p>
      )}

      {views.length > 1 && (
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-[0.2em] text-zinc-500">Pilihan rute</p>

          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
            {views.map((view) => {
              const active = view.index === selected.index;

              return (
                <button
                  key={view.index}
                  type="button"
                  aria-pressed={active}
                  onClick={() => onSelectRoute(view.index)}
                  className={`rounded-2xl border p-3 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400/60 ${
                    active ? 'border-emerald-400/60 bg-emerald-400/10' : 'border-line hover:border-emerald-400/30'
                  }`}
                >
                  <span className="flex items-center justify-between gap-2">
                    <span className="text-sm font-semibold text-zinc-100">{view.title}</span>
                    <RiskBadge level={view.status} label={ROUTE_STATUS_LABEL[view.status]} size="sm" />
                  </span>

                  <span className="mt-1.5 block text-xs text-zinc-400">
                    {formatDistanceKm(view.distanceKm)} · {formatDuration(view.durationMinutes)}
                    {view.extraMinutes !== null && ` · ${formatExtraMinutes(view.extraMinutes)}`}
                  </span>

                  {recommended === view.index && recommended !== 0 && (
                    <span className="mt-1.5 inline-block rounded-full bg-emerald-400/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-300">
                      Risiko lebih rendah
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          {data.safer_alternative_available && selected.index === 0 && recommended !== 0 && (
            <p className="mt-3 rounded-2xl border border-emerald-400/30 bg-emerald-400/5 px-4 py-3 text-sm leading-relaxed text-zinc-300">
              Ada rute alternatif dengan risiko tercatat lebih rendah
              {views[recommended]?.extraMinutes !== null && views[recommended]
                ? ` (${formatExtraMinutes(views[recommended].extraMinutes as number)})`
                : ''}
              .{' '}
              <button
                type="button"
                onClick={() => onSelectRoute(recommended)}
                className="font-semibold text-emerald-300 underline-offset-2 hover:underline"
              >
                Lihat {views[recommended]?.title.toLowerCase() ?? 'alternatif'}
              </button>
            </p>
          )}
        </div>
      )}

      <div className="rounded-2xl border border-line bg-ink/40 p-4">
        <div className="flex flex-wrap items-center gap-3">
          <RiskBadge level={selected.status} label={ROUTE_STATUS_LABEL[selected.status]} size="lg" />
          <span className="text-sm text-zinc-400">
            Skor tertinggi di jalur{' '}
            <strong className="text-zinc-100">{formatScore(selected.maxScore)}</strong> dari 10
          </span>
        </div>

        <p className="mt-3 text-sm leading-relaxed text-zinc-300">{STATUS_COPY[selected.status]}</p>

        <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
          <div>
            <dt className="text-xs text-zinc-500">Jarak</dt>
            <dd className="font-medium text-zinc-100">{formatDistanceKm(selected.distanceKm)}</dd>
          </div>
          <div>
            <dt className="text-xs text-zinc-500">Perkiraan waktu tempuh</dt>
            <dd className="font-medium text-zinc-100">{formatDuration(selected.durationMinutes)}</dd>
          </div>
          <div>
            <dt className="text-xs text-zinc-500">Jalur skor tinggi</dt>
            <dd className="font-medium text-zinc-100">{formatMeters(selected.highExposureM)}</dd>
          </div>
          <div>
            <dt className="text-xs text-zinc-500">Jalur skor sedang atau lebih</dt>
            <dd className="font-medium text-zinc-100">{formatMeters(selected.mediumExposureM)}</dd>
          </div>
          <div>
            <dt className="text-xs text-zinc-500">Kejadian tercatat di sekitar jalur</dt>
            <dd className="font-medium text-zinc-100">{selected.incidentCount}</dd>
          </div>
          <div>
            <dt className="text-xs text-zinc-500">Cakupan data</dt>
            <dd className="font-medium text-zinc-100">{formatPercent(selected.dataCoverage)}</dd>
          </div>
        </dl>

        <p className="mt-3 text-[11px] leading-relaxed text-zinc-500">
          Cakupan data = bagian titik pemeriksaan yang memiliki data kejadian di sekitarnya (radius 1,5 km). Tidak ada
          kejadian tercatat tidak sama dengan tidak ada kejadian.
        </p>
      </div>

      {(selected.dataLimited || notes.length > 0) && (
        <div className="space-y-2">
          {selected.dataLimited && (
            <p className="flex gap-2 rounded-2xl border border-amber-400/30 bg-amber-400/10 px-4 py-3 text-xs leading-relaxed text-amber-200">
              <AlertTriangle size={14} className="mt-0.5 shrink-0" aria-hidden="true" />
              Data kejadian di sekitar rute ini terbatas, sehingga hasil kurang dapat diandalkan.
            </p>
          )}

          {notes.map((note) => (
            <p key={note} className="flex gap-2 rounded-2xl border border-line px-4 py-3 text-xs leading-relaxed text-zinc-400">
              <Info size={14} className="mt-0.5 shrink-0 text-zinc-500" aria-hidden="true" />
              {note}
            </p>
          ))}
        </div>
      )}

      {selected.reasons.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-[0.2em] text-zinc-500">Alasan</h3>
          <ul className="mt-2 space-y-2 text-sm leading-relaxed text-zinc-300">
            {selected.reasons.map((reason) => (
              <li key={reason} className="flex gap-2">
                <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-zinc-600" aria-hidden="true" />
                {reason}
              </li>
            ))}
          </ul>
        </div>
      )}

      {selected.index === 0 && data.narrative && (
        <div className="rounded-2xl border border-line p-4">
          <h3 className="text-xs font-semibold uppercase tracking-[0.2em] text-zinc-500">Ringkasan AI</h3>
          <p className="mt-2 text-sm leading-relaxed text-zinc-300">{data.narrative}</p>
          <p className="mt-2 text-[11px] text-zinc-500">
            Dibuat otomatis dari hasil di atas; angka dan status tetap berasal dari data tercatat.
          </p>
        </div>
      )}

      <div>
        <h3 className="text-xs font-semibold uppercase tracking-[0.2em] text-zinc-500">
          Ruas jalan yang dilalui ({selected.segments.length})
        </h3>

        <ol className="mt-2 space-y-1.5">
          {shownSegments.map((segment) => {
            const focused = focusedSegment === segment.index;
            const category = categoryLabel(segment.dominant_category);

            return (
              <li key={segment.index}>
                <button
                  type="button"
                  aria-pressed={focused}
                  onClick={() => onFocusSegment(focused ? null : segment.index)}
                  className={`flex w-full items-stretch gap-3 rounded-xl border p-2.5 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400/60 ${
                    focused ? 'border-emerald-400/50 bg-emerald-400/10' : 'border-line hover:border-emerald-400/30'
                  }`}
                >
                  <span
                    className="w-1.5 shrink-0 rounded-full"
                    style={{ background: LEVEL_HEX[segment.risk_level] }}
                    aria-hidden="true"
                  />

                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium text-zinc-100">{roadLabel(segment)}</span>
                    <span className="block truncate text-xs text-zinc-500">
                      {[segment.place_name, formatMeters(segment.length_m)].filter(Boolean).join(' · ')}
                    </span>
                    {segment.incident_count > 0 && (
                      <span className="mt-0.5 block text-xs text-zinc-400">
                        {segment.incident_count} kejadian tercatat{category ? ` · ${category}` : ''}
                      </span>
                    )}
                  </span>

                  <span className="shrink-0 text-right text-xs">
                    <span className="block font-semibold" style={{ color: LEVEL_HEX[segment.risk_level] }}>
                      {LEVEL_TITLE[segment.risk_level]}
                    </span>
                    <span className="block text-zinc-500">{formatScore(segment.risk_score)}</span>
                  </span>
                </button>
              </li>
            );
          })}
        </ol>

        {hiddenSegments > 0 && (
          <button
            type="button"
            onClick={() => setShowAllSegments(true)}
            className="mt-2 text-xs font-semibold text-emerald-300 underline-offset-2 hover:underline"
          >
            Tampilkan {hiddenSegments} ruas lainnya
          </button>
        )}

        {showAllSegments && selected.segments.length > SEGMENTS_PREVIEW && (
          <button
            type="button"
            onClick={() => setShowAllSegments(false)}
            className="mt-2 block text-xs font-semibold text-emerald-300 underline-offset-2 hover:underline"
          >
            Ringkas daftar
          </button>
        )}
      </div>

      {selected.status !== 'aman' && (
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-[0.2em] text-zinc-500">Saran umum</h3>
          <ul className="mt-2 space-y-1.5 text-sm leading-relaxed text-zinc-400">
            {GENERAL_TIPS.map((tip) => (
              <li key={tip} className="flex gap-2">
                <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-zinc-600" aria-hidden="true" />
                {tip}
              </li>
            ))}
          </ul>
        </div>
      )}

      <p className="border-t border-line pt-4 text-xs leading-relaxed text-zinc-500">
        <strong className="text-zinc-400">Bukan jaminan keamanan.</strong> Hasil berdasarkan data kejadian yang tercatat di
        Gardu (pemberitaan dan laporan warga; sebagian data dapat berupa simulasi), bukan data resmi kepolisian, dan dapat
        belum lengkap. Tetap waspada, patuhi rambu lalu lintas, dan utamakan keselamatan Anda. Pembagian jam:{' '}
        {Object.values(TIME_BUCKET_INFO)
          .map((info) => `${info.label} ${info.range}`)
          .join(', ')}{' '}
        WIB.
      </p>
    </section>
  );
});

export default RouteResultPanel;
