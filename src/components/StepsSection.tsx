'use client';

import { useEffect, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import Reveal from '@/components/Reveal';
import { Zap } from 'react-feather';

const STEPS = [
  {
    n: '01',
    title: 'Warga melapor',
    desc: 'Isi formulir singkat: lokasi, waktu, deskripsi. Sepenuhnya anonim.',
  },
  {
    n: '02',
    title: 'AI memverifikasi',
    desc: 'Entitas diekstrak, laporan diklasterkan, duplikat ditandai.',
  },
  {
    n: '03',
    title: 'Skor diperbarui',
    desc: 'Insiden terverifikasi menaikkan skor kerawanan area & jam terkait.',
  },
  {
    n: '04',
    title: 'Komunitas terlindungi',
    desc: 'Peta publik dan Cek Rute memandu warga menjauhi zona rawan.',
  },
];

const STEP_DETAILS = [
  {
    title: 'Privasi warga tetap dijaga',
    desc: 'Laporan menjadi masukan sistem tanpa perlu menampilkan identitas pelapor.',
  },
  {
    title: 'Informasi penting terstruktur',
    desc: 'Sistem menyiapkan informasi yang dibutuhkan untuk tahap pemetaan risiko.',
  },
  {
    title: 'Pemetaan risiko berbasis laporan',
    desc: 'Skor area diperbarui sesuai insiden dan periode waktu yang relevan.',
  },
  {
    title: 'Informasi untuk keputusan yang lebih baik',
    desc: 'Warga dapat memeriksa informasi area dan mempertimbangkan rute perjalanan.',
  },
];

function ReportIllustration() {
  return (
    <div className="mx-auto w-full max-w-[290px]">
      <div className="rounded-2xl border border-emerald-400/20 bg-[#0b1717] p-3.5 shadow-2xl shadow-emerald-950/30 sm:p-4">
        <div className="flex items-center justify-between border-b border-white/[0.08] pb-3">
          <div>
            <p className="text-xs font-semibold text-white sm:text-sm">
              Laporan kejadian
            </p>
            <p className="mt-1 text-[10px] text-zinc-500">
              Formulir anonim
            </p>
          </div>

          <span className="rounded-full border border-emerald-400/20 bg-emerald-400/10 px-2.5 py-1 text-[9px] text-emerald-300">
            PRIVAT
          </span>
        </div>

        <div className="mt-3.5 space-y-3">
          <div>
            <p className="mb-1.5 text-[9px] uppercase tracking-widest text-zinc-500">
              Lokasi kejadian
            </p>
            <div className="flex items-center gap-2.5 rounded-lg border border-white/[0.08] bg-white/[0.025] p-2.5">
              <span className="text-sm text-emerald-300">⌖</span>
              <span className="text-xs text-zinc-300">
                Lokasi terlapor
              </span>
            </div>
          </div>

          <div>
            <p className="mb-1.5 text-[9px] uppercase tracking-widest text-zinc-500">
              Waktu kejadian
            </p>
            <div className="rounded-lg border border-white/[0.08] bg-white/[0.025] p-2.5 text-xs text-zinc-300">
              ◷ &nbsp; Waktu laporan
            </div>
          </div>

          <div>
            <p className="mb-1.5 text-[9px] uppercase tracking-widest text-zinc-500">
              Deskripsi
            </p>
            <div className="space-y-1.5 rounded-lg border border-white/[0.08] bg-white/[0.025] p-2.5">
              <div className="h-1.5 w-full rounded-full bg-zinc-700/70" />
              <div className="h-1.5 w-5/6 rounded-full bg-zinc-700/70" />
              <div className="h-1.5 w-2/3 rounded-full bg-zinc-700/70" />
            </div>
          </div>

          <motion.div
            animate={{ opacity: [0.75, 1, 0.75] }}
            transition={{ duration: 2, repeat: Infinity }}
            className="rounded-lg bg-emerald-400 py-2.5 text-center text-[10px] font-semibold text-[#06251c]"
          >
            ✓ &nbsp; Kirim laporan
          </motion.div>
        </div>
      </div>

      <motion.div
        animate={{ y: [0, -3, 0] }}
        transition={{ duration: 3, repeat: Infinity }}
        className="mt-2.5 flex items-center gap-2.5 rounded-xl border border-emerald-400/15 bg-emerald-400/[0.05] p-2.5"
      >
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-emerald-400/10 text-xs text-emerald-300">
          ✓
        </span>
        <div>
          <p className="text-[10px] font-medium text-white">
            Identitas terlindungi
          </p>
          <p className="mt-0.5 text-[9px] text-zinc-500">
            Laporan anonim
          </p>
        </div>
      </motion.div>
    </div>
  );
}

function AIIllustration() {
  const entities = [
    { label: 'Lokasi', value: 'Entitas lokasi terdeteksi' },
    { label: 'Waktu', value: 'Informasi waktu terdeteksi' },
    { label: 'Kategori', value: 'Jenis kejadian dikenali' },
  ];

  return (
    <div className="mx-auto w-full max-w-[290px]">
      <div className="rounded-2xl border border-emerald-400/20 bg-[#0b1717] p-3.5 shadow-2xl shadow-emerald-950/30 sm:p-4">
        <div className="flex items-center gap-3">
          <motion.div
            animate={{
              boxShadow: [
                '0 0 10px #10b98115',
                '0 0 25px #10b98145',
                '0 0 10px #10b98115',
              ],
            }}
            transition={{ duration: 2.5, repeat: Infinity }}
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-emerald-400/30 bg-emerald-400/10 text-sm font-bold text-emerald-300"
          >
            AI
          </motion.div>

          <div>
            <p className="text-xs font-semibold text-white sm:text-sm">
              Report Analysis
            </p>
            <p className="mt-1 text-[10px] text-zinc-500">
              Pemrosesan laporan
            </p>
          </div>

          <span className="ml-auto h-1.5 w-1.5 rounded-full bg-emerald-400" />
        </div>

        <div className="my-4 flex items-center gap-2">
          <div className="h-px flex-1 bg-emerald-400/20" />
          <motion.span
            animate={{ opacity: [0.4, 1, 0.4] }}
            transition={{ duration: 1.8, repeat: Infinity }}
            className="text-[9px] uppercase tracking-widest text-emerald-300"
          >
            Extracting entities
          </motion.span>
          <div className="h-px flex-1 bg-emerald-400/20" />
        </div>

        <div className="space-y-2">
          {entities.map((item, i) => (
            <motion.div
              key={item.label}
              initial={{ opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: i * 0.15 }}
              className="flex items-center justify-between gap-2 rounded-lg border border-white/[0.07] bg-white/[0.025] p-2.5"
            >
              <div>
                <p className="text-[9px] text-zinc-500">{item.label}</p>
                <p className="mt-1 text-[10px] text-zinc-300">
                  {item.value}
                </p>
              </div>
              <span className="text-xs text-emerald-300">✓</span>
            </motion.div>
          ))}
        </div>

        <div className="mt-3 rounded-lg border border-amber-400/15 bg-amber-400/[0.05] p-2.5">
          <p className="text-[10px] text-amber-200">
            Pemeriksaan duplikasi
          </p>
          <div className="mt-2 flex items-center gap-2">
            <div className="h-1 flex-1 overflow-hidden rounded-full bg-zinc-800">
              <motion.div
                animate={{ width: ['10%', '85%', '100%'] }}
                transition={{ duration: 3, repeat: Infinity }}
                className="h-full rounded-full bg-amber-300"
              />
            </div>
            <span className="text-[9px] text-zinc-500">Memeriksa</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function RiskIllustration() {
  return (
    <div className="mx-auto w-full max-w-[290px]">
      <div className="rounded-2xl border border-emerald-400/20 bg-[#0b1717] p-3.5 shadow-2xl shadow-emerald-950/30 sm:p-4">
        <div className="flex items-center justify-between gap-2">
          <div>
            <p className="text-xs font-semibold text-white sm:text-sm">
              Risk Monitoring
            </p>
            <p className="mt-1 text-[10px] text-zinc-500">
              Peta kerawanan area
            </p>
          </div>
          <span className="rounded-full border border-red-400/20 bg-red-400/10 px-2 py-1 text-[9px] text-red-300">
            Risk alert
          </span>
        </div>

        <div className="relative mt-3 h-36 overflow-hidden rounded-lg border border-white/[0.08] bg-[#0a2220] sm:h-40">
          <svg
            viewBox="0 0 320 220"
            className="h-full w-full"
            preserveAspectRatio="xMidYMid slice"
          >
            <defs>
              <pattern
                id="gardu-risk-grid"
                width="25"
                height="25"
                patternUnits="userSpaceOnUse"
              >
                <path
                  d="M25 0H0V25"
                  fill="none"
                  stroke="#24534b"
                  strokeWidth=".7"
                />
              </pattern>

              <radialGradient id="gardu-risk-glow">
                <stop offset="0%" stopColor="#ef4444" stopOpacity=".9" />
                <stop offset="55%" stopColor="#f97316" stopOpacity=".55" />
                <stop offset="100%" stopColor="#f97316" stopOpacity="0" />
              </radialGradient>
            </defs>

            <rect width="320" height="220" fill="url(#gardu-risk-grid)" />

            <path
              d="M-10 50L75 80L135 40L210 85L335 30 M10 220L95 145L170 170L245 120L330 165 M60 -10L95 70L65 130L120 230 M245 -10L210 55L250 105L220 230"
              fill="none"
              stroke="#34796a"
              strokeWidth="2"
              opacity=".7"
            />

            <ellipse
              cx="165"
              cy="100"
              rx="85"
              ry="65"
              fill="url(#gardu-risk-glow)"
            />
            <ellipse
              cx="215"
              cy="130"
              rx="48"
              ry="38"
              fill="url(#gardu-risk-glow)"
            />

            <circle cx="165" cy="100" r="7" fill="#fb7185" />

            <circle
              cx="165"
              cy="100"
              r="15"
              fill="none"
              stroke="#fb7185"
            >
              <animate
                attributeName="r"
                values="12;34;12"
                dur="2.5s"
                repeatCount="indefinite"
              />
              <animate
                attributeName="stroke-opacity"
                values=".8;0;.8"
                dur="2.5s"
                repeatCount="indefinite"
              />
            </circle>

            <rect
              x="180"
              y="25"
              width="120"
              height="30"
              rx="7"
              fill="#111f20"
              stroke="#fb7185"
              strokeOpacity=".5"
            />

            <text
              x="240"
              y="44"
              fill="#fda4af"
              fontSize="10"
              textAnchor="middle"
            >
              Zona terpantau
            </text>
          </svg>

          <div className="absolute bottom-2 left-2 rounded-lg border border-white/10 bg-[#081312]/90 px-2.5 py-1.5">
            <p className="text-[8px] uppercase tracking-wider text-zinc-500">
              Status area
            </p>
            <p className="mt-0.5 text-[10px] font-bold text-amber-300">
              Skor diperbarui
            </p>
          </div>
        </div>

        <div className="mt-3 space-y-2">
          {[
            ['Laporan terverifikasi', 'Memengaruhi skor area'],
            ['Periode waktu', 'Skor sesuai jam kejadian'],
          ].map(([label, value]) => (
            <div
              key={label}
              className="flex items-center gap-2.5 rounded-lg border border-white/[0.07] p-2.5"
            >
              <span className="text-xs text-emerald-300">↗</span>
              <div>
                <p className="text-[10px] font-medium text-zinc-200">
                  {label}
                </p>
                <p className="mt-0.5 text-[9px] text-zinc-500">{value}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function CommunityIllustration() {
  return (
    <div className="mx-auto w-full max-w-[290px]">
      <div className="rounded-2xl border border-emerald-400/20 bg-[#0b1717] p-3.5 shadow-2xl shadow-emerald-950/30 sm:p-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-xs font-semibold text-white sm:text-sm">
              Cek Rute
            </p>
            <p className="mt-1 text-[10px] text-zinc-500">
              Simulasi rute perjalanan
            </p>
          </div>
          <span className="text-base text-emerald-300">⌁</span>
        </div>

        <div className="relative mt-3 h-36 overflow-hidden rounded-lg border border-white/[0.08] bg-[#0a2220] sm:h-40">
          <svg viewBox="0 0 320 220" className="h-full w-full">
            <defs>
              <pattern
                id="gardu-route-grid"
                width="25"
                height="25"
                patternUnits="userSpaceOnUse"
              >
                <path
                  d="M25 0H0V25"
                  fill="none"
                  stroke="#24534b"
                  strokeWidth=".7"
                />
              </pattern>
            </defs>

            <rect width="320" height="220" fill="url(#gardu-route-grid)" />

            <path
              d="M0 55L60 55L90 90L150 90L185 40L245 40L275 75L320 75 M30 220L30 140L90 140L125 110L125 0 M190 220L190 145L230 115L230 80L280 80L300 120L320 120"
              fill="none"
              stroke="#39756b"
              strokeWidth="5"
              opacity=".45"
            />

            <path
              d="M35 170L85 170L120 140L160 140L190 105L250 105L285 65"
              fill="none"
              stroke="#34d399"
              strokeWidth="3"
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeDasharray="7 6"
            >
              <animate
                attributeName="stroke-dashoffset"
                from="52"
                to="0"
                dur="2s"
                repeatCount="indefinite"
              />
            </path>

            <circle cx="35" cy="170" r="8" fill="#34d399" />
            <circle cx="285" cy="65" r="8" fill="#e2e8f0" />

            <circle
              cx="35"
              cy="170"
              r="15"
              fill="none"
              stroke="#34d399"
            >
              <animate
                attributeName="r"
                values="9;20;9"
                dur="2s"
                repeatCount="indefinite"
              />
              <animate
                attributeName="stroke-opacity"
                values=".7;0;.7"
                dur="2s"
                repeatCount="indefinite"
              />
            </circle>
          </svg>

          <span className="absolute left-2 top-2 rounded-full border border-emerald-400/20 bg-[#081312]/90 px-2 py-1 text-[9px] text-emerald-300">
            Rute alternatif
          </span>
        </div>

        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="mt-3 flex items-center gap-2.5 rounded-lg border border-emerald-400/15 bg-emerald-400/[0.06] p-2.5"
        >
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-emerald-400/10 text-xs text-emerald-300">
            ✓
          </div>
          <div>
            <p className="text-[10px] font-semibold text-white">
              Informasi risiko tersedia
            </p>
            <p className="mt-0.5 text-[9px] text-zinc-500">
              Periksa kondisi area sebelum berangkat
            </p>
          </div>
        </motion.div>
      </div>
    </div>
  );
}

function StepIllustration({ step }: { step: number }) {
  const illustrations = [
    <ReportIllustration key="report" />,
    <AIIllustration key="ai" />,
    <RiskIllustration key="risk" />,
    <CommunityIllustration key="community" />,
  ];

  return (
<div className="relative flex h-[350px] w-full items-center justify-center overflow-hidden">
  <div className="w-full origin-center scale-[0.8]">
    {step === 0 && <ReportIllustration />}
    {step === 1 && <AIIllustration />}
    {step === 2 && <RiskIllustration />}
    {step === 3 && <CommunityIllustration />}
  </div>
</div>
  );
}

export default function HowItWorksSection() {
  const [activeStep, setActiveStep] = useState(0);
  const [paused, setPaused] = useState(false);

  useEffect(() => {
    if (paused) return;

    const timer = window.setInterval(() => {
      setActiveStep((current) => (current + 1) % STEPS.length);
    }, 5000);

    return () => window.clearInterval(timer);
  }, [paused]);

  const step = STEPS[activeStep];
  const detail = STEP_DETAILS[activeStep];

  const selectStep = (index: number) => {
    setActiveStep(index);
    setPaused(true);
  };

  return (
    <section className="container-x py-8 sm:py-10">
      <Reveal>
        <p className="text-[10px] mt-7 font-semibold uppercase tracking-[0.3em] text-emerald-400 sm:text-xs">
          Alur Sistem
        </p>

        <h2 className="mt-3 max-w-2xl font-display text-3xl font-bold text-white sm:text-4xl">
          Dari laporan menjadi peringatan.
        </h2>

        <p className="mt-3 pb-5 max-w-2xl text-sm leading-6 text-zinc-500 sm:mt-4 sm:text-base">
          Empat tahapan yang mengubah laporan warga menjadi informasi risiko
          dan panduan yang membantu komunitas mengambil keputusan.
        </p>
      </Reveal>

      <div
        className="mx-auto mt-5 max-w-5xl overflow-hidden rounded-2xl border border-line bg-panel/40 sm:mt-6"
        onMouseEnter={() => setPaused(true)}
        onMouseLeave={() => setPaused(false)}
        onFocusCapture={() => setPaused(true)}
        onBlurCapture={() => setPaused(false)}
      >
        <div className="grid lg:grid-cols-[1fr_0.95fr]">
          {/* LEFT: illustration */}
          <div className="relative flex items-center justify-center border-b border-line px-3 py-3 sm:px-5 lg:border-b-0 lg:border-r lg:p-4">
            <div className="absolute left-4 right-4 top-3 z-20 flex items-center justify-between sm:left-5 sm:right-5 sm:top-4">
              <span className="rounded-full border border-white/10 bg-black/30 px-2.5 py-1 text-[9px] uppercase tracking-[0.14em] text-zinc-400 backdrop-blur sm:text-[10px]">
                System walkthrough
              </span>

              <span className="font-mono text-[10px] text-emerald-300">
                {step.n} / 04
              </span>
            </div>

            <div className="w-full pt-7">
              <StepIllustration step={activeStep} />
            </div>
          </div>

          {/* RIGHT: step information */}
          <div className="flex min-w-0 flex-col justify-center p-4 sm:p-5 lg:p-6">
            <div className="mb-4 flex items-center gap-2">
              {STEPS.map((item, i) => (
                <button
                  key={item.n}
                  type="button"
                  aria-label={`Lihat langkah ${item.n}: ${item.title}`}
                  aria-current={activeStep === i ? 'step' : undefined}
                  onClick={() => selectStep(i)}
                  className={`h-1 flex-1 rounded-full transition-colors duration-300 ${
                    activeStep === i
                      ? 'bg-emerald-400'
                      : 'bg-white/10 hover:bg-white/25'
                  }`}
                />
              ))}
            </div>

            <AnimatePresence mode="wait">
              <motion.div
                key={activeStep}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -5 }}
                transition={{ duration: 0.25 }}
              >
                <p className="font-mono text-[10px] tracking-widest text-emerald-300 sm:text-xs">
                  STEP {step.n}
                </p>

                <h3 className="mt-2 font-display text-xl font-bold text-white sm:text-2xl">
                  {step.title}
                </h3>

                <p className="mt-2 text-xs leading-5 text-zinc-400 sm:text-sm sm:leading-6">
                  {step.desc}
                </p>

                <div className="mt-4 flex items-start gap-2.5 rounded-xl border border-emerald-400/15 bg-emerald-400/[0.04] p-3">
                  <span className="mt-0.5 shrink-0 text-emerald-300">
                    <Zap size={15} />
                  </span>

                  <div>
                    <p className="text-[11px] font-semibold leading-4 text-zinc-200 sm:text-xs">
                      {detail.title}
                    </p>
                    <p className="mt-2 text-[10px] leading-none text-zinc-500 sm:text-xs sm:leading-5">
                      {detail.desc}
                    </p>
                  </div>
                </div>
              </motion.div>
            </AnimatePresence>

            <div className="mt-4 flex items-center justify-between gap-3 border-t border-white/[0.07] pt-3">
              <button
                type="button"
                onClick={() =>
                  selectStep((activeStep - 1 + STEPS.length) % STEPS.length)
                }
                className="cursor-pointer text-[10px] text-zinc-500 transition hover:text-white sm:text-xs"
              >
                Sebelumnya
              </button>

              <button
                type="button"
                onClick={() =>
                  selectStep((activeStep + 1) % STEPS.length)
                }
                className="cursor-pointer inline-flex items-center gap-2 rounded-full border border-emerald-400/25 bg-emerald-400/[0.07] px-3 py-2 text-[10px] font-semibold text-emerald-300 transition hover:bg-emerald-400/15 sm:text-xs"
              >
                {activeStep === STEPS.length - 1
                  ? 'Ulangi alur'
                  : 'Langkah berikutnya'}
              </button>
            </div>
          </div>
        </div>

        {/* Auto-play progress */}
        <div className="h-0.5 bg-white/[0.04]">
          <motion.div
            key={activeStep}
            initial={{ width: '0%' }}
            animate={{ width: paused ? '100%' : '100%' }}
            transition={{
              duration: paused ? 0 : 3,
              ease: 'linear',
            }}
            className="h-full bg-emerald-400"
          />
        </div>
      </div>
    </section>
  );
}