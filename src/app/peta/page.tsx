'use client';

import { useEffect, useMemo, useState } from 'react';
import dynamic from 'next/dynamic';
import { motion } from 'framer-motion';

import Reveal from '@/components/Reveal';
import RiskBadge from '@/components/RiskBadge';
import {
  BACKEND_URL,
  BackendRiskLevel,
  TIME_BUCKETS,
  TimeBucket,
  currentTimeBucket,
  formatTimeBucket,
  readErrorDetail,
  toUiLevel,
} from '@/lib/api';
import { RiskPoint } from '@/lib/types';

const RiskMap = dynamic(
  () => import('@/components/RiskMap'),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-[540px] w-full items-center justify-center rounded-3xl border border-line bg-ink">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-emerald-400/30 border-t-emerald-400" />
      </div>
    ),
  },
);

type HeatmapCell = {
  area_name: string;
  latitude: number;
  longitude: number;
  risk_score: number;
  risk_level: BackendRiskLevel;
  contributing_incident_count: number;
};

type HeatmapResponse = {
  time_bucket: TimeBucket;
  cells: HeatmapCell[];
  updated_at: string | null;
};

export default function PetaPage() {
  const [selectedTimeSlot, setSelectedTimeSlot] =
    useState<TimeBucket>(currentTimeBucket());

  const [scores, setScores] = useState<RiskPoint[]>([]);

  const [loading, setLoading] = useState(true);

  const [error, setError] =
    useState<string | null>(null);

  // ==========================================
  // LOAD RISK DATA
  // ==========================================

  useEffect(() => {
    let alive = true;

    async function loadRiskScores() {
      setLoading(true);
      setError(null);

      try {
        const response = await fetch(
          `${BACKEND_URL}/risk/heatmap?time_bucket=${encodeURIComponent(
            selectedTimeSlot,
          )}`,
          {
            headers: { Accept: 'application/json' },
          },
        );

        if (!response.ok) {
          throw new Error(
            await readErrorDetail(
              response,
              'Gagal mengambil data kerawanan.',
            ),
          );
        }

        const data: HeatmapResponse =
          await response.json();

        const points: RiskPoint[] = data.cells
          .map((cell) => ({
            area_name: cell.area_name,
            lat: Number(cell.latitude),
            lng: Number(cell.longitude),
            score: Number(cell.risk_score),
            level: toUiLevel(cell.risk_level),
          }))
          .filter(
            (point) =>
              Number.isFinite(point.lat) &&
              Number.isFinite(point.lng) &&
              Number.isFinite(point.score),
          );

        if (!alive) return;

        setScores(points);
      } catch (err) {
        if (!alive) return;

        setError(
          err instanceof Error
            ? err.message
            : 'Gagal mengambil data kerawanan.',
        );

        setScores([]);
      } finally {
        if (alive) {
          setLoading(false);
        }
      }
    }

    loadRiskScores();

    return () => {
      alive = false;
    };
  }, [selectedTimeSlot]);

  // ==========================================
  // SORT
  // ==========================================

  const sorted = useMemo(
    () =>
      [...scores].sort(
        (a, b) =>
          b.score - a.score,
      ),
    [scores],
  );

  const top = sorted.slice(0, 3);

  const rawanCount =
    scores.filter(
      (s) => s.level === 'rawan',
    ).length;

  // ==========================================
  // UI
  // ==========================================

  return (
    <div className="container-x min-h-screen pb-24 pt-32">

      {/* HEADER */}
      <Reveal>
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.3em] text-emerald-400">
              Dasbor Publik
            </p>

            <h1 className="mt-3 font-display text-4xl font-bold text-white">
              Peta Kerawanan Yogyakarta
            </h1>

            <p className="mt-2 max-w-xl text-zinc-500">
              Heatmap skor kerawanan per
              area dan periode waktu.
            </p>
          </div>
        </div>
      </Reveal>

      {/* ERROR */}
      {error && (
        <Reveal delay={0.05}>
          <div className="mt-6 rounded-2xl border border-red-400/20 bg-red-400/5 p-4 text-sm text-red-300">
            <p className="font-semibold">
              Gagal mengambil data
              kerawanan
            </p>

            <p className="mt-1 text-xs text-red-300/70">
              {error}
            </p>
          </div>
        </Reveal>
      )}

      {/* TIME SLOT */}
      <Reveal delay={0.1}>
        <div className="glass-card mt-8 p-5">

          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs uppercase tracking-widest text-zinc-500">
                Periode waktu
              </p>

              <p className="mt-1 text-sm text-zinc-400">
                Pilih periode untuk melihat
                tingkat kerawanan.
              </p>
            </div>

            {loading && (
              <motion.span
                className="h-5 w-5 rounded-full border-2 border-emerald-400/30 border-t-emerald-400"
                animate={{
                  rotate: 360,
                }}
                transition={{
                  duration: 0.8,
                  repeat: Infinity,
                  ease: 'linear',
                }}
              />
            )}
          </div>

          <div className="mt-5 flex flex-wrap gap-2">
            {TIME_BUCKETS.map(
              (slot) => {
                const active =
                  selectedTimeSlot ===
                  slot;

                return (
                  <button
                    key={slot}
                    type="button"
                    onClick={() =>
                      setSelectedTimeSlot(
                        slot,
                      )
                    }
                    className={[
                      'rounded-xl px-4 py-2 text-sm font-medium transition cursor-pointer',

                      active
                        ? 'bg-emerald-400 text-ink shadow-glow'
                        : 'border border-line bg-ink/40 text-zinc-400 hover:border-emerald-400/30 hover:text-emerald-300',
                    ].join(' ')}
                  >
                    {formatTimeBucket(
                      slot,
                    )}
                  </button>
                );
              },
            )}
          </div>
        </div>
      </Reveal>

      {/* CONTENT */}
      <div className="mt-6 grid gap-6 lg:grid-cols-[1fr_320px]">

        {/* MAP */}
        <Reveal delay={0.15}>
          <div className="relative">

            {loading && (
              <div className="absolute inset-0 z-10 flex items-center justify-center rounded-3xl bg-ink/60 backdrop-blur-sm">
                <motion.span
                  className="h-8 w-8 rounded-full border-2 border-emerald-400/30 border-t-emerald-400"
                  animate={{
                    rotate: 360,
                  }}
                  transition={{
                    duration: 0.8,
                    repeat: Infinity,
                    ease: 'linear',
                  }}
                />
              </div>
            )}

            <RiskMap
              points={scores}
            />

            {/* LEGEND */}
            <div className="absolute bottom-4 left-4 z-[1000] rounded-2xl border border-line bg-ink/90 px-4 py-3 backdrop-blur">

              <p className="mb-2 text-[10px] font-semibold uppercase tracking-widest text-zinc-500">
                Legenda
              </p>

              <div className="space-y-1.5 text-xs text-zinc-400">

                <span className="flex items-center gap-2">
                  <i className="h-2.5 w-2.5 rounded-full bg-emerald-400" />
                  Aman (&lt;3)
                </span>

                <span className="flex items-center gap-2">
                  <i className="h-2.5 w-2.5 rounded-full bg-amber-400" />
                  Waspada (3–6,9)
                </span>

                <span className="flex items-center gap-2">
                  <i className="h-2.5 w-2.5 rounded-full bg-red-400" />
                  Rawan (7–10)
                </span>

              </div>
            </div>

          </div>
        </Reveal>

        {/* SIDEBAR */}
        <Reveal delay={0.2}>
          <div className="space-y-4">

            {/* SUMMARY */}
            <div className="glass-card p-5">

              <p className="text-xs uppercase tracking-widest text-zinc-500">
                Ringkasan{' '}
                {formatTimeBucket(
                  selectedTimeSlot,
                )}
              </p>

              <div className="mt-3 grid grid-cols-2 gap-3">

                <div className="rounded-2xl border border-line bg-ink/50 p-4">

                  <p className="font-display text-3xl font-bold text-red-300">
                    {rawanCount}
                  </p>

                  <p className="mt-1 text-xs text-zinc-500">
                    Zona rawan
                  </p>

                </div>

                <div className="rounded-2xl border border-line bg-ink/50 p-4">

                  <p className="font-display text-3xl font-bold text-emerald-300">
                    {scores.length}
                  </p>

                  <p className="mt-1 text-xs text-zinc-500">
                    Area terpantau
                  </p>

                </div>

              </div>
            </div>

            {/* TOP AREAS */}
            <div className="glass-card p-5">

              <p className="text-xs uppercase tracking-widest text-zinc-500">
                Skor tertinggi
              </p>

              {top.length === 0 ? (
                <p className="mt-4 text-sm text-zinc-600">
                  Belum ada data untuk
                  periode ini.
                </p>
              ) : (
                <ul className="mt-3 space-y-3">

                  {top.map(
                    (s, i) => (
                      <li
                        key={
                          s.area_name
                        }
                        className="flex items-center justify-between gap-3"
                      >

                        <div className="flex items-center gap-3">

                          <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-red-400/10 font-mono text-xs font-bold text-red-300 ring-1 ring-red-400/25">
                            {i + 1}
                          </span>

                          <span className="text-xs text-zinc-300">
                            {s.area_name}
                          </span>

                        </div>

                        <RiskBadge
                          level={
                            s.level
                          }
                          score={
                            s.score
                          }
                        />

                      </li>
                    ),
                  )}

                </ul>
              )}

            </div>

            {/* DISCLAIMER */}
            <div className="rounded-3xl border border-emerald-400/20 bg-emerald-400/5 p-5 text-xs leading-relaxed text-zinc-500">
              Data ditampilkan agregat
              per area, tanpa identitas
              individu mana pun
              (REQ-F-042). Skor bersifat
              prediktif, bukan klaim data
              resmi kepolisian.
            </div>

          </div>
        </Reveal>

      </div>
    </div>
  );
}