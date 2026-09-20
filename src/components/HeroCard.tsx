'use client';

import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import RiskBadge from '@/components/RiskBadge';

type RiskResponse = {
  area: string;
  time_slot: string;
  score: number;
};

type RiskLevel = 'aman' | 'waspada' | 'rawan';

const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000';

// ===============================
// KONFIGURASI KAWASAN
// ===============================
// Ganti dengan kawasan yang ingin
// ditampilkan pada HeroCard.
const TARGET_AREA = 'Kota Yogyakarta';

// ===============================
// MENENTUKAN TIME SLOT
// ===============================
function getTimeSlot(): string {
  const hour = new Date().getHours();

  if (hour >= 0 && hour < 6) {
    return 'dini_hari';
  }

  if (hour >= 6 && hour < 12) {
    return 'pagi';
  }

  if (hour >= 12 && hour < 15) {
    return 'siang';
  }

  if (hour >= 15 && hour < 18) {
    return 'sore';
  }

  return 'malam';
}

// ===============================
// MENENTUKAN LEVEL RISIKO
// ===============================
function getRiskLevel(score: number): RiskLevel {
  if (score >= 70) {
    return 'rawan';
  }

  if (score >= 40) {
    return 'waspada';
  }

  return 'aman';
}

// ===============================
// LABEL TIME SLOT
// ===============================
function getTimeSlotLabel(timeSlot: string): string {
  switch (timeSlot) {
    case 'dini_hari':
      return 'dini hari';

    case 'pagi':
      return 'pagi ini';

    case 'siang':
      return 'siang ini';

    case 'sore':
      return 'sore ini';

    case 'malam':
      return 'malam ini';

    default:
      return 'saat ini';
  }
}

export default function HeroCard() {
  const [risk, setRisk] = useState<RiskResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function fetchRisk() {
    try {
      setLoading(true);
      setError(null);

      const timeSlot = getTimeSlot();

      const response = await fetch(
        `${BACKEND_URL}/agents/risk?area=${encodeURIComponent(
          TARGET_AREA,
        )}&time_slot=${encodeURIComponent(timeSlot)}`,
        {
          method: 'GET',
          headers: {
            Accept: 'application/json',
          },
          cache: 'no-store',
        },
      );

      if (!response.ok) {
        throw new Error(
          `Backend mengembalikan status ${response.status}`,
        );
      }

      const data: RiskResponse = await response.json();

      setRisk(data);
    } catch (err) {
      console.error('Gagal mengambil risk prediction:', err);

      setError(
        err instanceof Error
          ? err.message
          : 'Gagal mengambil data risiko',
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const initialFetch = window.setTimeout(() => {
      void fetchRisk();
    }, 0);

    // Refresh setiap 5 menit
    const interval = setInterval(
      fetchRisk,
      5 * 60 * 1000,
    );

    return () => {
      window.clearTimeout(initialFetch);
      clearInterval(interval);
    };
  }, []);

  // ===============================
  // LOADING STATE
  // ===============================

  if (loading) {
    return (
      <div className="glass-card animate-floaty p-6 shadow-glow">
        <div className="flex items-center justify-between">
          <p className="text-xs uppercase tracking-widest text-zinc-500">
            Status kawasan
          </p>

          <span className="relative flex h-2.5 w-2.5">
            <span className="absolute h-full w-full animate-ping rounded-full bg-zinc-500 opacity-70" />
            <span className="relative h-2.5 w-2.5 rounded-full bg-zinc-500" />
          </span>
        </div>

        <p className="mt-5 font-display text-2xl font-bold text-white">
          Memuat data...
        </p>

        <div className="mt-5 h-2 overflow-hidden rounded-full bg-zinc-800">
          <motion.div
            initial={{ width: '0%' }}
            animate={{ width: '60%' }}
            transition={{
              duration: 1,
              repeat: Infinity,
              repeatType: 'reverse',
            }}
            className="h-full rounded-full bg-zinc-600"
          />
        </div>

        <p className="mt-4 text-xs leading-relaxed text-zinc-500">
          Mengambil prediksi risiko dari Risk Prediction Agent.
        </p>
      </div>
    );
  }

  // ===============================
  // ERROR STATE
  // ===============================

  if (error || !risk) {
    return (
      <div className="glass-card animate-floaty p-6 shadow-glow">
        <div className="flex items-center justify-between">
          <p className="text-xs uppercase tracking-widest text-zinc-500">
            Status kawasan
          </p>

          <span className="relative flex h-2.5 w-2.5">
            <span className="relative h-2.5 w-2.5 rounded-full bg-zinc-500" />
          </span>
        </div>

        <p className="mt-4 font-display text-xl font-bold text-white">
          Data belum tersedia
        </p>

        <p className="mt-3 text-xs leading-relaxed text-zinc-500">
          Risk Prediction Agent belum dapat memberikan skor
          untuk kawasan {TARGET_AREA}.
        </p>

        <button
          type="button"
          onClick={fetchRisk}
          className="mt-5 rounded-lg border border-zinc-700 bg-zinc-900 px-4 py-2 text-xs font-medium text-zinc-300 transition hover:border-zinc-500 hover:text-white"
        >
          Coba lagi
        </button>
      </div>
    );
  }

  // ===============================
  // DATA BERHASIL
  // ===============================

  const score = Math.max(
    0,
    Math.min(100, Number(risk.score)),
  );

  const level = getRiskLevel(score);

  const timeLabel = getTimeSlotLabel(
    risk.time_slot,
  );

  const isHighRisk = level === 'rawan';

  return (
    <div className="glass-card animate-floaty p-6 shadow-glow">
      {/* HEADER */}
      <div className="flex items-center justify-between">
        <p className="text-xs uppercase tracking-widest text-zinc-500">
          Status kawasan - {timeLabel}
        </p>

        <span className="relative flex h-2.5 w-2.5">
          <span
            className={`absolute h-full w-full animate-ping rounded-full ${
              isHighRisk
                ? 'bg-red-400'
                : level === 'waspada'
                  ? 'bg-amber-400'
                  : 'bg-emerald-400'
            } opacity-70`}
          />

          <span
            className={`relative h-2.5 w-2.5 rounded-full ${
              isHighRisk
                ? 'bg-red-400'
                : level === 'waspada'
                  ? 'bg-amber-400'
                  : 'bg-emerald-400'
            }`}
          />
        </span>
      </div>

      {/* AREA */}
      <p className="mt-3 font-display text-2xl font-bold text-white">
        {risk.area}
      </p>

      {/* SCORE */}
      <div className="mt-4 flex items-end gap-3">
        <motion.span
          className={`font-display text-5xl font-bold ${
            level === 'rawan'
              ? 'text-red-400'
              : level === 'waspada'
                ? 'text-amber-300'
                : 'text-emerald-300'
          }`}
          initial={{
            opacity: 0,
            scale: 0.8,
          }}
          animate={{
            opacity: 1,
            scale: 1,
          }}
          transition={{
            delay: 0.3,
            duration: 0.6,
            ease: [0.22, 1, 0.36, 1],
          }}
        >
          {Math.round(score)}
        </motion.span>

        <div className="pb-1.5">
          <RiskBadge level={level} />
        </div>
      </div>

      {/* PROGRESS BAR */}
      <div className="mt-5 h-2 overflow-hidden rounded-full bg-zinc-800">
        <motion.div
          initial={{ width: 0 }}
          animate={{
            width: `${score}%`,
          }}
          transition={{
            duration: 1.3,
            delay: 0.2,
            ease: 'easeOut',
          }}
          className="h-full rounded-full bg-gradient-to-r from-emerald-400 via-amber-400 to-red-400"
        />
      </div>

      {/* DESCRIPTION */}
      <p className="mt-4 text-xs leading-relaxed text-zinc-500">
        Skor prediktif per jam, diperbarui oleh Risk
        Prediction Agent.
      </p>

      {/* SOURCE INFO */}
      <div className="mt-4 flex items-center justify-between border-t border-zinc-800 pt-3">
        <span className="text-[10px] uppercase tracking-wider text-zinc-600">
          Risk Prediction Agent
        </span>

        <span className="text-[10px] text-zinc-600">
          {risk.time_slot}
        </span>
      </div>
    </div>
  );
}