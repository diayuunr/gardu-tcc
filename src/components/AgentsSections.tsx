'use client';

import { useRef } from 'react';
import {
  motion,
  useScroll,
  useTransform,
  MotionValue,
} from 'framer-motion';
import Reveal from './Reveal';

const AGENTS = [
  {
    name: 'Report Analysis Agent',
    role: 'Memahami & mengelompokkan laporan',
    desc: 'Gemini membaca laporan bebas dari warga dan mengubahnya menjadi data terstruktur (lokasi, waktu, dan jenis kejadian), lalu mendeteksi laporan serupa dalam 24 jam terakhir.',
    tag: 'Gemini API',
    accent: '#34d399',
  },
  {
    name: 'Risk Prediction Agent',
    role: 'Skor kerawanan per area & periode waktu',
    desc: 'Menghitung skor kerawanan 0-10 per area dan periode waktu dari kejadian terdokumentasi, lalu menyimpannya untuk peta dan cek rute.',
    tag: 'Berbasis aturan',
    accent: '#67e8f9',
  },
  {
    name: 'Safe Route Advisor',
    role: 'Cek risiko sebelum berangkat',
    desc: 'Mencocokkan asal dan tujuan dengan skor kerawanan area pada periode keberangkatan, lalu memberi status aman, waspada, atau berisiko tinggi.',
    tag: 'Berbasis aturan',
    accent: '#c4b5fd',
  },
];

function AgentCard({
  agent,
  index,
  progress,
}: {
  agent: (typeof AGENTS)[number];
  index: number;
  progress: MotionValue<number>;
}) {
  // Awalnya bertumpuk di tengah, lalu menyebar sesuai scroll.
  const x = useTransform(
    progress,
    [0, 0.35, 1],
    [index === 0 ? -14 : index === 2 ? 14 : 0, index === 0 ? -340 : index === 2 ? 340 : 0, index === 0 ? -340 : index === 2 ? 340 : 0],
  );

  const rotate = useTransform(
    progress,
    [0, 0.35, 1],
    [(index - 1) * 3, index === 0 ? -5 : index === 2 ? 5 : 0, index === 0 ? -5 : index === 2 ? 5 : 0],
  );

  const y = useTransform(
    progress,
    [0, 0.35, 1],
    [index === 1 ? 0 : 10, 0, 0],
  );

  const scale = useTransform(
    progress,
    [0, 0.35],
    [index === 1 ? 1 : 0.96, 1],
  );

  const zIndex = index === 1 ? 3 : index === 0 ? 2 : 1;

  return (
    <motion.article
      style={{ x, y, rotate, scale, zIndex }}
      className="absolute left-1/2 top-1/2 w-[min(86vw,350px)] -translate-x-1/2 -translate-y-1/2"
    >
      <div className="group relative flex min-h-[330px] flex-col overflow-hidden rounded-[26px] border border-white/10 bg-gradient-to-br from-[#14221c] via-[#0c1210] to-[#080c0b] p-6 shadow-[0_24px_80px_rgba(0,0,0,0.5)] backdrop-blur-xl transition-colors duration-300 hover:border-emerald-300/30 sm:min-h-[350px] sm:p-7">
        <div
          className="pointer-events-none absolute -right-16 -top-16 h-48 w-48 rounded-full blur-[75px] opacity-[0.12]"
          style={{ backgroundColor: agent.accent }}
        />

        <div className="relative flex items-center justify-between gap-3">
          <span
            className="rounded-full border px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider sm:text-xs"
            style={{
              color: agent.accent,
              borderColor: `${agent.accent}40`,
              backgroundColor: `${agent.accent}12`,
            }}
          >
            Agent {index + 1}
          </span>

          <span className="font-mono text-[10px] text-zinc-500 sm:text-xs">
            {agent.tag}
          </span>
        </div>

        <div className="relative mt-7 flex items-start gap-4">
          <div
            className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl border bg-black/20 font-display text-xl font-bold sm:h-14 sm:w-14 sm:text-2xl"
            style={{
              color: agent.accent,
              borderColor: `${agent.accent}30`,
            }}
          >
            0{index + 1}
          </div>

          <div className="min-w-0 pt-1">
            <h3 className="font-display text-lg font-bold leading-snug text-white sm:text-xl">
              {agent.name}
            </h3>
            <p
              className="mt-2 text-xs font-medium leading-relaxed sm:text-sm"
              style={{ color: agent.accent }}
            >
              {agent.role}
            </p>
          </div>
        </div>

        <div
          className="relative my-5 h-px"
          style={{
            background: `linear-gradient(to right, ${agent.accent}60, rgba(255,255,255,0.08), transparent)`,
          }}
        />

        <p className="relative text-sm leading-6 text-zinc-400">
          {agent.desc}
        </p>

        <div className="relative mt-auto flex items-center justify-between pt-6">
          <span className="text-[9px] uppercase tracking-[0.15em] text-zinc-600 sm:text-[10px]">
            Gardu Intelligence
          </span>

          <div className="flex items-center gap-1.5">
            {[0, 1, 2].map((dot) => (
              <motion.span
                key={dot}
                animate={{ opacity: [0.3, 1, 0.3] }}
                transition={{
                  duration: 1.8,
                  repeat: Infinity,
                  delay: dot * 0.25,
                }}
                className="h-1.5 w-1.5 rounded-full"
                style={{ backgroundColor: agent.accent }}
              />
            ))}
          </div>
        </div>
      </div>
    </motion.article>
  );
}

export default function AgentsSections() {
  const sectionRef = useRef<HTMLElement>(null);

  const { scrollYProgress } = useScroll({
    target: sectionRef,
    offset: ['start start', 'end end'],
  });

  const headingOpacity = useTransform(
    scrollYProgress,
    [0, 0.12, 0.3],
    [1, 1, 0.75],
  );

  const hintOpacity = useTransform(
    scrollYProgress,
    [0, 0.15, 0.4],
    [1, 1, 0],
  );

  return (
    <section
      ref={sectionRef}
      className="relative border-y border-line bg-panel/40"
    >
      {/* Header */}
      <div className="container-x pt-14 sm:pt-16">
        <Reveal>
          <p className="text-xs font-semibold uppercase tracking-[0.3em] text-emerald-400">
            Arsitektur Sistem
          </p>

          <h2 className="mt-3 max-w-2xl font-display text-3xl font-bold text-white sm:text-4xl">
            Tiga Agent dengan peran terpisah.
          </h2>

          <p className="mt-3 max-w-2xl text-sm leading-6 text-zinc-500 sm:mt-4 sm:text-base">
            Gemini digunakan untuk memahami laporan, sedangkan dua agen
            berbasis aturan menghitung skor kerawanan dan memeriksa rute.
          </p>
        </Reveal>
      </div>

      {/* Scroll stage */}
      <div className="relative mt-5 h-[125vh] sm:mt-7 sm:h-[135vh]">
        <div className="sticky top-0 flex h-screen max-h-[800px] min-h-[540px] flex-col items-center justify-start overflow-hidden px-4 mt-15 sm:pt-10">
          <motion.div
            style={{ opacity: headingOpacity }}
            className="relative z-10 mb-4 text-center sm:mb-5"
          >
            <span className="inline-flex items-center gap-2 rounded-full border border-emerald-400/15 bg-emerald-400/[0.05] px-3 py-1.5 text-[9px] font-semibold uppercase tracking-[0.2em] text-emerald-300 sm:px-4 sm:py-2 sm:text-xs">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
              Multi-Agent Architecture
            </span>

            <p className="mt-2 text-[10px] text-zinc-500 sm:mt-3 sm:text-xs">
              Scroll ke bawah untuk membuka deck
            </p>
          </motion.div>

          {/* Card stack */}
          <div className="relative mx-auto h-[370px] w-full max-w-[1080px] sm:h-[390px]">
            {AGENTS.map((agent, index) => (
              <AgentCard
                key={agent.name}
                agent={agent}
                index={index}
                progress={scrollYProgress}
              />
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
