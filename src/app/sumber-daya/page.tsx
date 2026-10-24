
'use client';

import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import Reveal from '@/components/Reveal';

interface Resource {
  category: 'Darurat' | 'Pengaduan' | 'Rehabilitasi' | 'Pemantau Independen';
  title: string;
  contact: string;
  description: string;
  question: string;
}

const RESOURCES: Resource[] = [
  {
    category: 'Darurat',
    title: 'Call Center Polri',
    contact: '110',
    description:
      'Layanan kepolisian untuk melaporkan situasi darurat, ancaman keselamatan, atau tindak kejahatan yang sedang terjadi.',
    question: 'Ada situasi darurat?',
  },
  {
    category: 'Darurat',
    title: 'PSC 112 DIY',
    contact: '112',
    description:
      'Pusat panggilan darurat terpadu Daerah Istimewa Yogyakarta untuk membantu penanganan kecelakaan, bencana, dan kondisi darurat.',
    question: 'Butuh bantuan darurat?',
  },
  {
    category: 'Pengaduan',
    title: 'Satpol PP DIY',
    contact: '(0274) 5021060',
    description:
      'Kanal pengaduan terkait ketertiban umum dan keamanan wilayah. Periksa kanal resmi Satpol PP DIY untuk memastikan prosedur pengaduan yang tersedia.',
    question: 'Ingin melapor gangguan?',
  },
  {
    category: 'Pengaduan',
    title: 'Hotline KemenPPPA',
    contact: '129',
    description:
      'Layanan pengaduan dan bantuan terkait kekerasan terhadap perempuan dan anak, termasuk kebutuhan perlindungan korban.',
    question: 'Perlu perlindungan korban?',
  },
  {
    category: 'Rehabilitasi',
    title: 'Dinas Sosial DIY',
    contact: '(0274) 514932',
    description:
      'Kanal koordinasi untuk mencari informasi mengenai pendampingan sosial dan program rehabilitasi bagi remaja.',
    question: 'Mencari pendampingan sosial?',
  },
  {
    category: 'Rehabilitasi',
    title: 'Balai Rehabilitasi Sosial Anak',
    contact: 'Kementerian Sosial RI',
    description:
      'Informasi layanan rehabilitasi sosial dan pendampingan bagi anak yang membutuhkan dukungan sosial. Hubungi kanal resmi untuk mengetahui layanan yang sesuai.',
    question: 'Butuh rehabilitasi remaja?',
  },
  {
    category: 'Pemantau Independen',
    title: 'Jogja Police Watch',
    contact: 'Kanal media sosial JPW',
    description:
      'Lembaga pemantau independen yang dapat menjadi rujukan untuk mengikuti informasi, laporan, dan perhatian publik terkait isu kepolisian di DI Yogyakarta.',
    question: 'Ingin memantau kasus?',
  },
];

const CATEGORY_STYLE: Record<Resource['category'], string> = {
  Darurat:
    'border-rose-400/30 bg-rose-400/10 text-rose-300',
  Pengaduan:
    'border-amber-400/30 bg-amber-400/10 text-amber-300',
  Rehabilitasi:
    'border-emerald-400/30 bg-emerald-400/10 text-emerald-300',
  'Pemantau Independen':
    'border-sky-400/30 bg-sky-400/10 text-sky-300',
};

const CATEGORY_DOT: Record<Resource['category'], string> = {
  Darurat: 'bg-rose-400',
  Pengaduan: 'bg-amber-400',
  Rehabilitasi: 'bg-emerald-400',
  'Pemantau Independen': 'bg-sky-400',
};

// Posisi kartu mengelilingi pusat halaman pada desktop.
const ORBIT_POSITIONS = [
  { top: '4%', left: '50%', x: '-50%', y: '0%' },
  { top: '20%', left: '80%', x: '-50%', y: '0%' },
  { top: '57%', left: '87%', x: '-50%', y: '-50%' },
  { top: '80%', left: '68%', x: '-50%', y: '-50%' },
  { top: '80%', left: '32%', x: '-50%', y: '-50%' },
  { top: '57%', left: '13%', x: '-50%', y: '-50%' },
  { top: '20%', left: '20%', x: '-50%', y: '0%' },
];

export default function SumberDayaPage() {
  const [selected, setSelected] = useState<number | null>(null);

  const activeResource =
    selected !== null ? RESOURCES[selected] : null;

  const isPhoneNumber = (contact: string) =>
    /^[\d()+\-\s]+$/.test(contact);

  return (
    <main className="relative min-h-screen overflow-hidden bg-gradient-to-br from-black via-[#0b2924] to-[#102f35] pb-20 pt-28 text-white">
      {/* Background glow */}
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute -left-32 top-20 h-80 w-80 rounded-full bg-emerald-500/10 blur-[100px]" />
        <div className="absolute -right-32 top-1/3 h-96 w-96 rounded-full bg-cyan-400/10 blur-[120px]" />
        <div className="absolute bottom-0 left-1/3 h-72 w-72 rounded-full bg-teal-400/10 blur-[100px]" />
        <div className="absolute inset-0 bg-black/40" />
        <div
          className="absolute inset-0 opacity-[0.07]"
          style={{
            backgroundImage:
              'radial-gradient(circle, #a7f3d0 1px, transparent 1px)',
            backgroundSize: '30px 30px',
          }}
        />
      </div>

      <div className="container-x relative z-10 mx-auto max-w-7xl px-5">
        {/* Header */}
        <Reveal>
          <div className="mx-auto max-w-2xl text-center">
            <motion.div
              initial={{ opacity: 0, y: 15 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6 }}
              className="mb-5 inline-flex items-center gap-2 rounded-full border border-emerald-300/20 bg-emerald-300/[0.08] px-4 py-2 text-xs font-semibold uppercase tracking-[0.22em] text-emerald-300"
            >
              <span className="h-2 w-2 animate-pulse rounded-full bg-emerald-400" />
              Gardu Resource Center
            </motion.div>

            <h1 className="font-display font-bold leading-tight tracking-tight text-5xl">
              Temukan <br className="hidden sm:block" />
              <span className="block bg-gradient-to-r from-emerald-300 via-teal-200 to-cyan-300 bg-clip-text text-transparent">
                Bantuan di Sekitarmu
              </span>
            </h1>

            <p className="mx-auto mt-5 max-w-2xl text-xs leading-snug text-slate-300 sm:text-base">
              Pilih pertanyaan di sekeliling halaman untuk menemukan
              kontak darurat, kanal pengaduan, pendampingan sosial,
              dan informasi pemantauan kasus kejahatan jalanan.
            </p>
          </div>
        </Reveal>

        {/* Interactive orbit desktop */}
        <section
          aria-label="Pilih kebutuhan bantuan"
          className="relative mx-auto mt-12 hidden h-[650px] max-w-6xl lg:block"
        >
          {/* Orbit rings */}
          <motion.div
            animate={{ rotate: 360 }}
            transition={{
              duration: 100,
              repeat: Infinity,
              ease: 'linear',
            }}
            className="pointer-events-none absolute left-1/2 top-1/2 h-[490px] w-[490px] -translate-x-1/2 -translate-y-1/2 rounded-full border border-dashed border-emerald-300/15"
          />

          <motion.div
            animate={{ rotate: -360 }}
            transition={{
              duration: 75,
              repeat: Infinity,
              ease: 'linear',
            }}
            className="pointer-events-none absolute left-1/2 top-1/2 h-[390px] w-[390px] -translate-x-1/2 -translate-y-1/2 rounded-full border border-teal-200/10"
          />

          {/* Center panel */}
          <div className="absolute left-1/2 top-1/2 z-20 w-[340px] -translate-x-1/2 -translate-y-1/2">
            <motion.div
              layout
              className="relative overflow-hidden rounded-[30px] border border-emerald-200/20 bg-gradient-to-br from-[#123b32]/95 via-[#102e2b]/95 to-[#153f48]/95 p-7 text-center shadow-[0_20px_90px_rgba(16,185,129,0.12)] backdrop-blur-2xl"
            >
              <div className="pointer-events-none absolute -right-12 -top-12 h-32 w-32 rounded-full bg-emerald-300/10 blur-2xl" />
              <div className="pointer-events-none absolute -bottom-16 -left-10 h-36 w-36 rounded-full bg-cyan-300/10 blur-2xl" />

              <AnimatePresence mode="wait">
                {activeResource ? (
                  <motion.div
                    key={activeResource.title}
                    initial={{ opacity: 0, y: 12, scale: 0.97 }}
                    animate={{ opacity: 1, y: 0, scale: 1 }}
                    exit={{ opacity: 0, y: -8 }}
                    transition={{ duration: 0.25 }}
                    className="relative"
                  >
                    <span
                      className={`inline-flex rounded-full border px-3 py-1 text-[10px] font-semibold uppercase tracking-wider ${CATEGORY_STYLE[activeResource.category]}`}
                    >
                      {activeResource.category}
                    </span>

                    <h2 className="mt-4 font-display text-xl font-bold">
                      {activeResource.title}
                    </h2>

                    <p className="mt-3 break-words font-mono text-xl font-bold text-emerald-300">
                      {activeResource.contact}
                    </p>

                    <p className="mt-3 text-xs leading-snug text-slate-300">
                      {activeResource.description}
                    </p>

                    {isPhoneNumber(activeResource.contact) ? (
                      <a
                        href={`tel:${activeResource.contact.replace(/[^\d+]/g, '')}`}
                        className="mt-5 inline-flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-emerald-400 to-teal-300 px-4 py-3 text-sm font-bold text-[#08251f] transition hover:brightness-110"
                      >
                        <span>Hubungi Kontak</span>
                      </a>
                    ) : (
                      <p className="mt-5 rounded-xl border border-white/10 bg-white/[0.04] px-3 py-3 text-xs text-slate-300">
                        Cari kanal resmi untuk informasi lebih lanjut.
                      </p>
                    )}

                    <button
                      type="button"
                      onClick={() => setSelected(null)}
                      className="mt-3 text-xs text-emerald-200/70 transition hover:text-emerald-200 cursor-pointer"
                    >
                      Kembali ke semua pilihan
                    </button>
                  </motion.div>
                ) : (
                  <motion.div
                    key="welcome"
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: 0.3 }}
                    className="relative"
                  >
                    <motion.div
                      animate={{ y: [0, -5, 0], rotate: [0, -4, 4, 0] }}
                      transition={{
                        duration: 4,
                        repeat: Infinity,
                        ease: 'easeInOut',
                      }}
                      className="mx-auto flex h-16 w-16 items-center justify-center rounded-2xl border border-emerald-200/20 bg-gradient-to-br from-emerald-300/20 to-cyan-300/10 text-3xl shadow-lg shadow-emerald-400/10"
                    >
                      🧭
                    </motion.div>

                    <p className="mt-5 text-xs font-semibold uppercase tracking-[0.2em] text-emerald-300">
                      Pusat Bantuan Gardu
                    </p>

                    <h2 className="mt-2 font-display text-2xl font-bold">
                      Temukan Bantuanmu
                    </h2>

                    <p className="mt-3 text-sm leading-snug text-slate-300">
                      Klik salah satu pertanyaan di sekeliling
                      untuk melihat informasi kontak yang sesuai.
                    </p>

                    <div className="mt-5 flex items-center justify-center gap-2 text-xs text-emerald-200/70">
                      <motion.span
                        animate={{ x: [0, 4, 0] }}
                        transition={{
                          duration: 1.5,
                          repeat: Infinity,
                        }}
                      >
                        ←
                      </motion.span>
                      Pilih pertanyaan
                      <motion.span
                        animate={{ x: [0, -4, 0] }}
                        transition={{
                          duration: 1.5,
                          repeat: Infinity,
                        }}
                      >
                        →
                      </motion.span>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </motion.div>
          </div>

          {/* Orbit question cards */}
          {RESOURCES.map((resource, index) => {
            const pos = ORBIT_POSITIONS[index];
            const active = selected === index;

            return (
              <motion.button
                key={resource.title}
                type="button"
                aria-pressed={active}
                onClick={() => setSelected(index)}
                initial={{ opacity: 0, scale: 0.7 }}
                animate={{
                  opacity: 1,
                  scale: active ? 1.06 : 1,
                  y: [0, index % 2 === 0 ? -7 : 7, 0],
                }}
                transition={{
                  opacity: { duration: 0.45, delay: index * 0.08 },
                  scale: { duration: 0.25 },
                  y: {
                    duration: 3 + (index % 3),
                    repeat: Infinity,
                    ease: 'easeInOut',
                    delay: index * 0.15,
                  },
                }}
                whileHover={{
                  scale: 1.08,
                  zIndex: 30,
                }}
                whileTap={{ scale: 0.96 }}
                style={{
                  position: 'absolute',
                  top: pos.top,
                  left: pos.left,
                  x: pos.x,
                  y: pos.y,
                }}
                className={`group z-10 w-[205px] rounded-2xl border p-4 text-left shadow-xl backdrop-blur-xl transition-colors duration-300 ${
                  active
                    ? 'border-emerald-300/70 bg-emerald-300/15 shadow-emerald-400/10'
                    : 'border-white/10 bg-[#12312f]/90 hover:border-emerald-300/40 hover:bg-[#19433c]/95'
                }`}
              >
                <div className="flex items-start gap-2.5">
                  <span
                    className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-full ${CATEGORY_DOT[resource.category]} ${active ? 'animate-pulse' : ''}`}
                  />
                  <div className="min-w-0">
                    <p className="text-sm font-semibold leading-5 text-white">
                      {resource.question}
                    </p>
                    <p className="mt-2 text-[10px] leading-4 text-slate-400 transition-colors group-hover:text-emerald-200">
                      {resource.title}
                    </p>
                  </div>
                </div>
              </motion.button>
            );
          })}
        </section>

        {/* Responsive interactive layout for mobile and tablet */}
        <section className="mt-10 lg:hidden">
          <div className="mx-auto mb-7 max-w-md">
            <motion.div
              layout
              className="rounded-3xl border border-emerald-200/20 bg-gradient-to-br from-[#123b32]/95 to-[#153f48]/95 p-6 text-center shadow-xl shadow-emerald-900/20 backdrop-blur-xl"
            >
              <AnimatePresence mode="wait">
                {activeResource ? (
                  <motion.div
                    key={activeResource.title}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -8 }}
                    transition={{ duration: 0.25 }}
                  >
                    <span
                      className={`inline-flex rounded-full border px-3 py-1 text-[10px] font-semibold uppercase tracking-wider ${CATEGORY_STYLE[activeResource.category]}`}
                    >
                      {activeResource.category}
                    </span>

                    <h2 className="mt-4 text-xl font-bold">
                      {activeResource.title}
                    </h2>

                    <p className="mt-2 break-words font-mono text-lg font-bold text-emerald-300">
                      {activeResource.contact}
                    </p>

                    <p className="mt-3 text-sm leading-6 text-slate-300">
                      {activeResource.description}
                    </p>

                    {isPhoneNumber(activeResource.contact) ? (
                      <a
                        href={`tel:${activeResource.contact.replace(/[^\d+]/g, '')}`}
                        className="mt-5 inline-flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-emerald-400 to-teal-300 px-4 py-3 text-sm font-bold text-[#08251f]"
                      >
                        Hubungi Kontak
                      </a>
                    ) : (
                      <p className="mt-5 rounded-xl border border-white/10 bg-white/[0.04] px-3 py-3 text-xs text-slate-300">
                        Cari kanal resmi untuk informasi lebih lanjut.
                      </p>
                    )}

                    <button
                      type="button"
                      onClick={() => setSelected(null)}
                      className="mt-4 text-xs text-emerald-200"
                    >
                      ← Lihat semua pertanyaan
                    </button>
                  </motion.div>
                ) : (
                  <motion.div
                    key="mobile-welcome"
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0 }}
                  >
                    <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl border border-emerald-200/20 bg-emerald-300/10 text-3xl">
                      🧭
                    </div>
                    <h2 className="mt-4 text-xl font-bold">
                      Pusat Bantuan Gardu
                    </h2>
                    <p className="mt-2 text-sm leading-6 text-slate-300">
                      Pilih pertanyaan untuk menemukan informasi
                      dan kontak yang kamu butuhkan.
                    </p>
                  </motion.div>
                )}
              </AnimatePresence>
            </motion.div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            {RESOURCES.map((resource, index) => {
              const active = selected === index;

              return (
                <motion.button
                  key={resource.title}
                  type="button"
                  aria-pressed={active}
                  onClick={() => setSelected(index)}
                  initial={{ opacity: 0, y: 15 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.35, delay: index * 0.05 }}
                  whileTap={{ scale: 0.98 }}
                  className={`rounded-2xl border p-4 text-left transition-all duration-300 ${
                    active
                      ? 'border-emerald-300/60 bg-emerald-300/10 shadow-lg shadow-emerald-900/20'
                      : 'border-white/10 bg-white/[0.035] hover:border-emerald-300/30 hover:bg-white/[0.06]'
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <span
                      className={`h-2 w-2 rounded-full ${CATEGORY_DOT[resource.category]}`}
                    />
                    <span
                      className={`text-[10px] font-semibold uppercase tracking-wider ${CATEGORY_STYLE[resource.category].split(' ').slice(-1)[0]}`}
                    >
                      {resource.category}
                    </span>
                  </div>

                  <h3 className="mt-3 text-sm font-semibold leading-6 text-white">
                    {resource.question}
                  </h3>

                  <div className="mt-2 flex items-center justify-between gap-3">
                    <span className="text-xs text-slate-400">
                      {resource.title}
                    </span>
                    <span className="text-emerald-300">
                      {active ? '✓' : '↗'}
                    </span>
                  </div>
                </motion.button>
              );
            })}
          </div>
        </section>

        {/* Safety note */}
        <Reveal delay={0.2}>
          <div className="mx-auto mt-12 max-w-4xl rounded-2xl border border-amber-300/15 bg-amber-300/[0.045] p-5 sm:p-6">
            <div className="flex items-start gap-3">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-amber-300/20 bg-amber-300/10 text-lg">
                ⚠️
              </span>
              <div>
                <h3 className="text-sm font-bold text-amber-200">
                  Gunakan kanal bantuan dengan bijak
                </h3>
                <p className="mt-2 text-xs leading-6 text-slate-300 sm:text-sm">
                  Gardu mengutamakan keselamatan, pelaporan yang
                  bertanggung jawab, dan pendampingan. Jangan menyebarkan
                  identitas terduga pelaku, melakukan pelacakan pribadi,
                  atau menghakimi seseorang tanpa proses yang semestinya.
                  Untuk keadaan darurat, prioritaskan keselamatan dan
                  hubungi layanan resmi.
                </p>
              </div>
            </div>
          </div>
        </Reveal>
      </div>
    </main>
  );
}