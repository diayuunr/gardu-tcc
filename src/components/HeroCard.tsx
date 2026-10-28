'use client';

import { motion } from 'framer-motion';

import RiskBadge from '@/components/RiskBadge';
import { useApiQuery } from '@/hooks/useApiQuery';
import type { RiskScore } from '@/lib/api-types';
import { formatScore } from '@/lib/format';
import { LEVEL_STYLE, TIME_BUCKET_INFO, normalizeLevel } from '@/lib/risk';

// Titik pusat Kota Yogyakarta yang ditanyakan ke GET /risk/score (backend memetakannya ke sel grid ±1 km).
const TARGET_LAT = -7.7956;
const TARGET_LON = 110.3695;

function Shell({ caption, children }: { caption: string; children: React.ReactNode }) {
  return (
    <div className="glass-card animate-floaty p-6 shadow-glow">
      <p className="text-xs uppercase tracking-widest text-zinc-500">{caption}</p>
      {children}
    </div>
  );
}

/** Kartu status area pusat kota di landing. Jujur: tanpa data = "belum ada data", bukan "aman". */
export default function HeroCard() {
  const { data, loading, error, retry } = useApiQuery<RiskScore>(
    '/risk/score',
    { lat: TARGET_LAT, lon: TARGET_LON },
    'Skor kawasan belum dapat dimuat.',
  );

  if (loading) {
    return (
      <Shell caption="Status kawasan">
        <div className="mt-5 space-y-3" role="status" aria-label="Memuat status kawasan">
          <div className="h-7 w-48 animate-pulse rounded bg-zinc-800 motion-reduce:animate-none" />
          <div className="h-12 w-32 animate-pulse rounded bg-zinc-800 motion-reduce:animate-none" />
          <div className="h-2 animate-pulse rounded-full bg-zinc-800 motion-reduce:animate-none" />
        </div>
      </Shell>
    );
  }

  if (error || !data) {
    return (
      <Shell caption="Status kawasan">
        <p className="mt-4 font-display text-xl font-bold text-white">Pusat Kota Yogyakarta</p>
        <p className="mt-3 text-sm leading-relaxed text-zinc-400" role="alert">
          {error ?? 'Skor kawasan belum dapat dimuat.'}
        </p>
        <button type="button" onClick={retry} className="btn-ghost mt-4 !px-4 !py-2 text-xs">
          Coba lagi
        </button>
      </Shell>
    );
  }

  const bucket = TIME_BUCKET_INFO[data.time_bucket];
  const caption = `Status kawasan · ${bucket.label.toLowerCase()} (${bucket.range} WIB)`;

  if (!data.has_data) {
    return (
      <Shell caption={caption}>
        <p className="mt-4 font-display text-2xl font-bold text-white">Pusat Kota Yogyakarta</p>
        <p className="mt-3 text-lg font-semibold text-zinc-300">Belum ada data</p>
        <p className="mt-2 text-sm leading-relaxed text-zinc-500">
          Belum ada kejadian tercatat untuk area dan periode jam ini. <strong className="text-zinc-400">Ini bukan berarti aman</strong>,
          hanya belum ada data yang cukup untuk dinilai.
        </p>
        <p className="mt-4 border-t border-zinc-800 pt-3 text-[10px] text-zinc-600">Area ±1 km di sekitar titik pusat kota.</p>
      </Shell>
    );
  }

  const score = Math.max(0, Math.min(10, Number(data.risk_score)));
  const ui = normalizeLevel(data.risk_level);
  const style = LEVEL_STYLE[ui];

  return (
    <Shell caption={caption}>
      <p className="mt-3 font-display text-2xl font-bold text-white">Pusat Kota Yogyakarta</p>
      <p className="mt-0.5 text-xs text-zinc-500">{data.label}</p>

      <div className="mt-4 flex items-end gap-3">
        <motion.span
          className={`font-display text-5xl font-bold ${style.text}`}
          initial={{ opacity: 0, scale: 0.8 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 0.3, duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
        >
          {formatScore(score)}
        </motion.span>
        <div className="pb-1.5">
          <RiskBadge level={data.risk_level} />
        </div>
      </div>

      <div
        className="mt-5 h-2 overflow-hidden rounded-full bg-zinc-800"
        role="img"
        aria-label={`Skor ${formatScore(score)} dari 10`}
      >
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${score * 10}%` }}
          transition={{ duration: 1.3, delay: 0.2, ease: 'easeOut' }}
          className="h-full rounded-full bg-gradient-to-r from-emerald-400 via-amber-400 to-red-400"
        />
      </div>

      <p className="mt-4 text-xs leading-relaxed text-zinc-500">
        Skor 0-10 dari riwayat kejadian tercatat di area ±1 km pusat kota pada periode jam ini
        {data.contributing_incident_count > 0 ? ` (${data.contributing_incident_count} kejadian tercatat)` : ''}. Bukan prediksi
        pasti dan bukan jaminan keamanan.
      </p>

      <div className="mt-4 flex items-center justify-between border-t border-zinc-800 pt-3 text-[10px] uppercase tracking-wider text-zinc-600">
        <span>Perhitungan berbasis aturan</span>
        <span>{bucket.label}</span>
      </div>
    </Shell>
  );
}
