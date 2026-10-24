
'use client';

import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import Link from 'next/link';
import Reveal from './Reveal';
import { ArrowRightCircle, ArrowUpLeft } from 'react-feather';

const FEATURES = [
  {
    title: 'Pelaporan Anonim',
    desc: 'Laporkan titik rawan dengan cepat tanpa perlu membuat akun atau membagikan identitas.',
    icon: 'M16 7a4 4 0 11-8 0 4 4 0 018 0zM4 21a8 8 0 0116 0',
    href: '/lapor',
  },
  {
    title: 'Ekstraksi & Klasterisasi AI',
    desc: 'AI mengekstrak lokasi, waktu, jenis kejadian, lalu mengelompokkan laporan.',
    icon: 'M9 12l2 2 4-4M12 3l7 4v5c0 5-3.2 8.6-7 10-3.8-1.4-7-5-7-10V7l7-4z',
    href: '/lapor',
  },
  {
    title: 'Prediksi Zona Rawan',
    desc: 'Kenali area dan waktu yang berpotensi rawan berdasarkan pola laporan yang terkumpul.',
    icon: 'M3 17l6-6 4 4 8-8M21 7v6h-6',
    href: '/peta',
  },
  {
    title: 'Cek Rute Aman',
    desc: 'Masukkan titik awal dan tujuan untuk melihat area rawan di sepanjang perjalanan.',
    icon: 'M9 20l-5.45-2.72A1 1 0 014 16.38V5.62a1 1 0 011.45-.9L9 7m0 13l6-3m-6 3V7m6 10l4.55 2.28a1 1 0 001.45-.9V8.62a1 1 0 00-.55-.9L15 5m0 12V5m0 0L9 7',
    href: '/rute',
  },
  {
    title: 'Peta Heatmap Publik',
    desc: 'Lihat sebaran titik rawan melalui peta interaktif yang dapat diakses siapa saja.',
    icon: 'M9 20l-5.45-2.72A1 1 0 014 16.38V5.62a1 1 0 011.45-.9L9 7m0 13l6-3m-6 3V7m6 10l4.55 2.28a1 1 0 001.45-.9V8.62a1 1 0 00-.55-.9L15 5m0 12V5m0 0L9 7',
    href: '/peta',
  },
  {
    title: 'Sumber Daya & Kontak',
    desc: 'Akses cepat ke satgas, layanan pengaduan, dan program rehabilitasi remaja.',
    icon: 'M3 5a2 2 0 012-2h3.3a1 1 0 01.9.7L10.6 7a1 1 0 01-.3 1.1L8.2 9.9a14 14 0 006.9 6.9l1.8-2.1a1 1 0 011.1-.3l3.3 1.3a1 1 0 01.7.9V19a2 2 0 01-2 2h-1C9.7 21 3 14.3 3 6V5z',
    href: '/sumber-daya',
  },
];

function FeatureIllustration({ index }: { index: number }) {
  return (
    <div className="relative flex min-h-[310px] w-full items-center justify-center overflow-hidden rounded-3xl border border-white/[0.08] bg-gradient-to-br from-[#101c18] via-[#080e0c] to-[#0b1c1c] p-6 sm:p-9">
      {/* Decorative background */}
      <div className="pointer-events-none absolute inset-0 opacity-[0.06]"
        style={{
          backgroundImage:
            'radial-gradient(circle, #a7f3d0 1px, transparent 1px)',
          backgroundSize: '22px 22px',
        }}
      />

      <motion.div
        className="pointer-events-none absolute h-48 w-48 rounded-full bg-emerald-400/[0.10] blur-[80px]"
        animate={{
          scale: [1, 1.3, 1],
          opacity: [0.35, 0.75, 0.35],
        }}
        transition={{
          duration: 4,
          repeat: Infinity,
          ease: 'easeInOut',
        }}
      />

      <AnimatePresence mode="wait">
        <motion.div
          key={index}
          initial={{ opacity: 0, y: 20, scale: 0.94 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: -12, scale: 0.97 }}
          transition={{ duration: 0.3, ease: 'easeOut' }}
          className="relative z-10 w-full max-w-sm"
        >
          {/* 01 — Anonymous reporting */}
          {index === 0 && (
            <div className="rounded-2xl border border-white/10 bg-[#101714]/95 p-5 shadow-2xl">
              <div className="flex items-center justify-between">
                <span className="text-sm font-semibold text-white">
                  Buat Laporan
                </span>
                <span className="rounded-full bg-emerald-400/10 px-3 py-1 text-[10px] text-emerald-300">
                  Anonim
                </span>
              </div>

              <div className="mt-5 space-y-3">
                <div className="rounded-xl border border-white/[0.08] p-3">
                  <p className="text-[10px] text-zinc-500">Lokasi kejadian</p>
                  <div className="mt-2 flex items-center gap-2 text-xs text-zinc-200">
                    <span className="text-emerald-300">📍</span>
                    Lokasi laporan terdeteksi
                  </div>
                </div>

                <div className="rounded-xl border border-white/[0.08] p-3">
                  <p className="text-[10px] text-zinc-500">Deskripsi</p>
                  <div className="mt-3 space-y-2">
                    <div className="h-2 w-full rounded-full bg-white/10" />
                    <div className="h-2 w-4/5 rounded-full bg-white/10" />
                  </div>
                </div>

                <motion.div
                  animate={{ opacity: [0.6, 1, 0.6] }}
                  transition={{ duration: 2, repeat: Infinity }}
                  className="rounded-xl bg-emerald-400 px-4 py-3 text-center text-xs font-bold text-[#07130e]"
                >
                  Kirim laporan →
                </motion.div>
              </div>
            </div>
          )}

          {/* 02 — AI extraction */}
          {index === 1 && (
            <div className="rounded-2xl border border-white/10 bg-[#101714]/95 p-5 shadow-2xl">
              <div className="flex items-center justify-between">
                <span className="text-sm font-semibold text-white">
                  AI Report Analysis
                </span>
                <span className="text-[10px] text-emerald-300">Processing</span>
              </div>

              <div className="mt-5 rounded-xl border border-white/[0.08] p-4">
                <p className="text-[11px] leading-6 text-zinc-400">
                  Kejadian dilaporkan terjadi di sekitar jalan utama pada
                  malam hari.
                </p>
                <motion.div
                  initial={{ x: '-100%' }}
                  animate={{ x: ['-100%', '100%'] }}
                  transition={{
                    duration: 2,
                    repeat: Infinity,
                    ease: 'easeInOut',
                  }}
                  className="mt-4 h-0.5 w-1/3 rounded-full bg-emerald-300"
                />
              </div>

              <div className="mt-4 grid grid-cols-3 gap-2">
                {['Lokasi', 'Waktu', 'Kejadian'].map((label, i) => (
                  <motion.div
                    key={label}
                    animate={{ borderColor: ['#263b31', '#34d399', '#263b31'] }}
                    transition={{
                      duration: 2.5,
                      delay: i * 0.35,
                      repeat: Infinity,
                    }}
                    className="rounded-xl border bg-emerald-400/[0.04] p-3 text-center"
                  >
                    <span className="text-[10px] text-emerald-200">{label}</span>
                  </motion.div>
                ))}
              </div>

              <div className="mt-3 rounded-xl border border-emerald-400/15 bg-emerald-400/[0.05] p-3 text-[10px] text-zinc-300">
                Laporan siap dikelompokkan
              </div>
            </div>
          )}

          {/* 03 — Risk prediction */}
          {index === 2 && (
            <div className="rounded-2xl border border-white/10 bg-[#101714]/95 p-5 shadow-2xl">
              <div className="flex items-center justify-between">
                <span className="text-sm font-semibold text-white">
                  Prediksi Risiko
                </span>
                <span className="text-[10px] text-zinc-500">Analisis pola</span>
              </div>

              <div className="mt-6 flex h-36 items-end justify-around gap-3 rounded-xl border border-white/[0.06] bg-white/[0.02] px-4 pb-3 pt-5">
                {[32, 50, 40, 72, 56, 94, 68].map((height, i) => (
                  <motion.div
                    key={i}
                    initial={{ height: 0 }}
                    animate={{ height: `${height}%` }}
                    transition={{ duration: 0.7, delay: i * 0.08 }}
                    className={`w-full max-w-7 rounded-t-md ${
                      height >= 70
                        ? 'bg-gradient-to-t from-rose-500/40 to-rose-400'
                        : height >= 50
                          ? 'bg-gradient-to-t from-amber-500/40 to-amber-300'
                          : 'bg-gradient-to-t from-emerald-500/40 to-emerald-300'
                    }`}
                  />
                ))}
              </div>

              <div className="mt-4 flex items-center gap-3 rounded-xl bg-rose-400/[0.07] p-3">
                <motion.span
                  animate={{ scale: [1, 1.2, 1] }}
                  transition={{ duration: 1.5, repeat: Infinity }}
                  className="h-2.5 w-2.5 rounded-full bg-rose-400"
                />
                <div>
                  <p className="text-xs font-semibold text-white">
                    Zona perlu perhatian
                  </p>
                  <p className="mt-1 text-[10px] text-zinc-500">
                    Ilustrasi visualisasi risiko
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* 04 — Safe route */}
          {index === 3 && (
            <div className="rounded-2xl border border-white/10 bg-[#101714]/95 p-5 shadow-2xl">
              <div className="text-sm font-semibold text-white">
                Rute Perjalanan
              </div>

              <div className="relative mt-5 h-40 overflow-hidden rounded-xl border border-white/[0.06] bg-[#14201a]">
                <svg viewBox="0 0 320 160" className="h-full w-full" fill="none">
                  <path
                    d="M0 35L70 50L110 20L180 48L225 20L320 48M0 105L65 90L125 125L190 85L245 120L320 90M55 0L75 160M165 0L180 160M260 0L240 160"
                    stroke="#29483b"
                    strokeWidth="2"
                  />
                  <motion.path
                    d="M35 120C65 105 65 55 120 65S190 120 220 75S260 40 290 35"
                    stroke="#34d399"
                    strokeWidth="4"
                    strokeLinecap="round"
                    strokeDasharray="7 7"
                    animate={{ strokeDashoffset: [0, -28] }}
                    transition={{ duration: 2, repeat: Infinity, ease: 'linear' }}
                  />
                  <circle cx="35" cy="120" r="6" fill="#34d399" />
                  <circle cx="290" cy="35" r="6" fill="#67e8f9" />
                  <motion.circle
                    cx="120"
                    cy="65"
                    r="10"
                    fill="#f87171"
                    opacity="0.7"
                    animate={{ r: [8, 15, 8], opacity: [0.7, 0.15, 0.7] }}
                    transition={{ duration: 2, repeat: Infinity }}
                  />
                </svg>
              </div>

              <div className="mt-4 flex items-center justify-between text-[10px]">
                <span className="text-emerald-300">● Titik awal</span>
                <span className="text-cyan-300">● Tujuan</span>
                <span className="text-rose-300">● Zona rawan</span>
              </div>
            </div>
          )}

          {/* 05 — Public heatmap */}
          {index === 4 && (
            <div className="rounded-2xl border border-white/10 bg-[#101714]/95 p-5 shadow-2xl">
              <div className="flex items-center justify-between">
                <span className="text-sm font-semibold text-white">
                  Heatmap Publik
                </span>
                <span className="text-[10px] text-emerald-300">Peta risiko</span>
              </div>

              <div className="relative mt-5 h-40 overflow-hidden rounded-xl border border-white/[0.06] bg-[#14201a]">
                <svg viewBox="0 0 320 160" className="h-full w-full" fill="none">
                  <path
                    d="M0 35L70 50L110 20L180 48L225 20L320 48M0 105L65 90L125 125L190 85L245 120L320 90M55 0L75 160M165 0L180 160M260 0L240 160"
                    stroke="#345347"
                    strokeWidth="2"
                  />
                  {[
                    [70, 50, 18],
                    [140, 85, 25],
                    [215, 45, 21],
                    [250, 110, 17],
                  ].map(([cx, cy, r], i) => (
                    <motion.circle
                      key={i}
                      cx={cx}
                      cy={cy}
                      r={r}
                      fill={i === 1 ? '#fb7185' : i === 2 ? '#fbbf24' : '#34d399'}
                      animate={{ opacity: [0.12, 0.35, 0.12], r: [r * 0.8, r, r * 0.8] }}
                      transition={{ duration: 2.5, delay: i * 0.3, repeat: Infinity }}
                    />
                  ))}
                </svg>
              </div>

              <div className="mt-4 flex gap-3 text-[10px] text-zinc-400">
                <span>Rendah</span>
                <div className="h-2 flex-1 rounded-full bg-gradient-to-r from-emerald-400 via-amber-300 to-rose-400" />
                <span>Tinggi</span>
              </div>
            </div>
          )}

          {/* 06 — Resources and contacts */}
          {index === 5 && (
            <div className="rounded-2xl border border-white/10 bg-[#101714]/95 p-5 shadow-2xl">
              <div className="text-sm font-semibold text-white">
                Pusat Bantuan
              </div>

              <div className="mt-5 space-y-3">
                {[
                  ['Darurat', 'Call center dan bantuan cepat', 'bg-rose-400'],
                  ['Pengaduan', 'Kanal pelaporan resmi', 'bg-amber-400'],
                  ['Rehabilitasi', 'Pendampingan sosial', 'bg-emerald-400'],
                ].map(([title, desc, color], i) => (
                  <motion.div
                    key={title}
                    initial={{ opacity: 0, x: 15 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: i * 0.15 }}
                    className="flex items-center gap-3 rounded-xl border border-white/[0.07] bg-white/[0.025] p-3"
                  >
                    <span className={`h-8 w-1 rounded-full ${color}`} />
                    <div>
                      <p className="text-xs font-semibold text-white">{title}</p>
                      <p className="mt-1 text-[10px] text-zinc-500">{desc}</p>
                    </div>
                    <span className="ml-auto text-emerald-300">↗</span>
                  </motion.div>
                ))}
              </div>
            </div>
          )}
        </motion.div>
      </AnimatePresence>
    </div>
  );
}

export const FeaturesSection = () => {
  const [activeIndex, setActiveIndex] = useState<number | null>(null);

  const selectedIndex = activeIndex ?? 0;

  return (
    <section className="relative overflow-hidden py-24">
      <div className="container-x mx-auto">
        <Reveal>
          <p className="text-xs font-semibold uppercase tracking-[0.3em] text-emerald-400">
            Fitur Utama
          </p>

          <h2 className="mt-3 max-w-2xl font-display text-3xl font-bold text-white sm:text-4xl">
            Satu platform,
            <br />
            dari laporan menuju keselamatan.
          </h2>

          <p className="mt-4 max-w-xl text-sm leading-snug text-zinc-400">
            Semua yang kamu butuhkan untuk memahami risiko, melaporkan
            kejadian, dan membangun lingkungan yang lebih aman.
          </p>
        </Reveal>

        <div className="mt-12 grid items-center gap-10 lg:grid-cols-[0.9fr_1.1fr] lg:gap-16">
          {/* Feature list: compact numbered rows */}
          <div className="divide-y divide-white/[0.08]">
            {FEATURES.map((feature, index) => {
              const isActive = activeIndex === index;

              return (
                <Link
                  key={feature.title}
                  href={feature.href}
                  onMouseEnter={() => setActiveIndex(index)}
                  onFocus={() => setActiveIndex(index)}
                  onClick={() => setActiveIndex(index)}
                  className={`group flex items-start gap-4 py-5 transition-colors duration-300 ${
                    isActive ? 'text-white' : 'text-zinc-400'
                  }`}
                >
                  <motion.span
                    animate={{
                      color: isActive ? '#6ee7b7' : '#71717a',
                      scale: isActive ? 1.08 : 1,
                    }}
                    className="w-8 shrink-0 pt-0.5 font-mono text-sm font-semibold"
                  >
                    {String(index + 1).padStart(2, '0')}
                  </motion.span>

                  <div className="min-w-0 flex-1">
                    <h3 className="text-base font-semibold transition-colors duration-300 group-hover:text-emerald-300 sm:text-lg">
                      {feature.title}
                    </h3>

                    <AnimatePresence initial={false}>
                      {isActive && (
                        <motion.p
                          initial={{ opacity: 0, height: 0, y: -5 }}
                          animate={{ opacity: 1, height: 'auto', y: 0 }}
                          exit={{ opacity: 0, height: 0, y: -5 }}
                          transition={{ duration: 0.25 }}
                          className="max-w-md overflow-hidden pt-2 text-sm leading-6 text-zinc-400"
                        >
                          {feature.desc}
                        </motion.p>
                      )}
                    </AnimatePresence>
                  </div>

                  <motion.span
                    animate={{
                      opacity: isActive ? 1 : 0.3,
                      x: isActive ? 0 : -4,
                    }}
                    className="pt-0.5 text-lg text-emerald-300"
                  >
                    <ArrowRightCircle size={18} />
                  </motion.span>
                </Link>
              );
            })}
          </div>

          {/* Illustration panel: changes on hover */}
          <div className="hidden lg:block">
            <AnimatePresence mode="wait">
              {activeIndex !== null && (
                <motion.div
                  key={selectedIndex}
                  initial={{ opacity: 0, x: 18 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -12 }}
                  transition={{ duration: 0.25 }}
                >
                  <FeatureIllustration index={selectedIndex} />
                </motion.div>
              )}
            </AnimatePresence>

            {activeIndex === null && (
              <div className="flex min-h-[310px] items-center justify-center rounded-3xl border border-dashed border-white/10 bg-white/[0.015]">
                <div className="text-center">
                  <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl border border-emerald-300/15 bg-emerald-400/[0.05] text-2xl text-emerald-300">
                   <ArrowUpLeft size={24} />
                  </div>
                  <p className="mt-4 text-sm font-medium text-zinc-300">
                    Jelajahi fitur Gardu
                  </p>
                  <p className="mt-2 text-xs text-zinc-500">
                    Arahkan kursor ke nomor fitur untuk melihat ilustrasi
                  </p>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Mobile: no permanent illustration panel; tap a feature to reveal it */}
        <div className="mt-6 lg:hidden">
          <AnimatePresence mode="wait">
            {activeIndex !== null && (
              <motion.div
                key={selectedIndex}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                transition={{ duration: 0.25 }}
              >
                <FeatureIllustration index={selectedIndex} />
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </section>
  );
};
