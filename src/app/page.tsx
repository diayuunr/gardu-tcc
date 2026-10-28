import Link from 'next/link';
import Reveal from '@/components/Reveal';
import HeroCard from '@/components/HeroCard';
import { createClient } from '@/lib/supabase/server';
import CountUp from '@/components/CountUp';
import { FeaturesSection } from '@/components/FeaturesSection';
import AgentsSections from '@/components/AgentsSections';
import HowItWorksSection from '@/components/StepsSection';

export const dynamic = 'force-dynamic';

<<<<<<< HEAD
const FEATURES = [
  {
    title: 'Pelaporan Anonim',
    desc: 'Laporkan indikasi kerawanan kurang dari 1 menit. Tanpa akun, tanpa identitas.',
    icon: 'M16 7a4 4 0 11-8 0 4 4 0 018 0zM4 21a8 8 0 0116 0',
    href: '/lapor',
  },
  {
    title: 'Verifikasi & Klasterisasi AI',
    desc: 'AI mengekstrak lokasi, waktu, jenis kejadian, lalu mengelompokkan laporan serupa via embedding pgvector.',
    icon: 'M9 12l2 2 4-4M12 3l7 4v5c0 5-3.2 8.6-7 10-3.8-1.4-7-5-7-10V7l7-4z',
    href: '/lapor',
  },
  {
    title: 'Prediksi Zona Rawan',
    desc: 'Skor kerawanan per area & jam dari seed data + laporan terverifikasi, termasuk pola musiman.',
    icon: 'M3 17l6-6 4 4 8-8M21 7v6h-6',
    href: '/peta',
  },
  {
    title: 'Cek Rute Aman',
    desc: 'Asal, tujuan, jam berangkat, sistem memperingatkan zona berisiko beserta saran.',
    icon: 'M9 20l-5.45-2.72A1 1 0 014 16.38V5.62a1 1 0 011.45-.9L9 7m0 13l6-3m-6 3V7m6 10l4.55 2.28a1 1 0 001.45-.9V8.62a1 1 0 00-.55-.9L15 5m0 12V5m0 0L9 7',
    href: '/rute',
  },
  {
    title: 'Peta Heatmap Publik',
    desc: 'Dasbor peta interaktif tanpa login, kesadaran situasional untuk seluruh warga.',
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

const AGENTS = [
  {
    name: 'Report Verification Agent',
    role: 'Ekstraksi & klasterisasi laporan',
    desc: 'Teks bebas menjadi data terstruktur + embedding vector(768), lalu mengelompokkan insiden serupa dengan cosine similarity untuk menyaring duplikat/hoaks.',
    tag: 'LangChain + pgvector',
  },
  {
    name: 'Risk Prediction Agent',
    role: 'Skor kerawanan per area & jam',
    desc: 'Mengagregasi seed data dan laporan terverifikasi menjadi skor 0-10 per area/jam, dengan koreksi pola musiman seperti lonjakan menjelang Ramadan.',
    tag: 'Seed data + komunitas',
  },
  {
    name: 'Safe Route Advisor',
    role: 'Peringatan dini perjalanan',
    desc: 'Memeriksa rute terhadap peta skor kerawanan pada jam keberangkatan, lalu memberi status aman/waspada/rawan beserta area yang dihindari.',
    tag: 'Sampling geodesi rute',
  },
];

=======
>>>>>>> origin/main
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

export default async function LandingPage() {
  const supabase = await createClient();
  const [{ count: totalReports }, { data: riskRows }] =
    await Promise.all([
      supabase
        .from('reports')
        .select('*', {
          count: 'exact',
          head: true,
        }),

      supabase
        .from('risk_scores')
        .select('area_name'),
    ]);

  const monitoredAreas = new Set(
    (riskRows ?? [])
      .map((row) => row.area_name)
      .filter(Boolean),
  ).size;

  const riskPredictions = riskRows?.length ?? 0;

  return (
    <div>
      {/* HERO */}
      <section className="relative overflow-hidden pb-24 pt-30">
        <div className="pointer-events-none absolute inset-0">
          <div className="absolute -top-32 left-1/2 h-[480px] w-[720px] -translate-x-1/2 rounded-full bg-emerald-500/10 blur-3xl" />

          <div className="absolute right-0 top-40 h-72 w-72 animate-blob rounded-full bg-teal-500/10 blur-3xl" />

          <div
            className="absolute inset-0 opacity-[0.13]"
            style={{
              backgroundImage:
                'linear-gradient(rgba(52,211,153,0.25) 1px, transparent 1px), linear-gradient(90deg, rgba(52,211,153,0.25) 1px, transparent 1px)',
              backgroundSize: '56px 56px',
              maskImage:
                'radial-gradient(ellipse 80% 60% at 50% 0%, black, transparent)',
              WebkitMaskImage:
                'radial-gradient(ellipse 80% 60% at 50% 0%, black, transparent)',
            }}
          />
        </div>

        <div className="container-x relative grid items-center gap-14 lg:grid-cols-[1.15fr_0.85fr]">
          <div>
            <Reveal>
              <span className="inline-flex items-center gap-2 rounded-full border border-emerald-400/25 bg-emerald-400/5 px-4 py-1.5 text-xs font-medium tracking-wide text-emerald-300">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                Sistem Kesadaran Komunitas - Yogyakarta
              </span>
            </Reveal>

            <Reveal delay={0.1}>
              <h1 className="mt-6 font-display text-5xl font-bold leading-[1.05] tracking-tight text-white sm:text-6xl lg:text-7xl">
                Tahu Jalannya,
                <br />
                <span className="text-gradient">Tahu Risikonya.</span>
              </h1>
            </Reveal>

            <Reveal delay={0.2}>
              <p className="mt-6 max-w-xl text-md leading-relaxed text-zinc-400">
                Gardu membantu warga dan mahasiswa lebih waspada saat beraktivitas di <br></br>D. I. Yogyakarta, mulai dari melaporkan kejadian secara anonim, mengenali area rawan, hingga memeriksa kondisi rute sebelum berangkat.
              </p>
            </Reveal>

            <Reveal delay={0.3}>
              <div className="mt-9 flex flex-wrap gap-4">
                <Link href="/lapor" className="btn-primary">
                  <svg
                    width="17"
                    height="17"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="M12 5v14M5 12h14" />
                  </svg>
                  Lapor Kejadian
                </Link>

                <Link href="/peta" className="btn-ghost">
                  Lihat Peta Kerawanan

                  <svg
                    width="17"
                    height="17"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="M5 12h14M13 6l6 6-6 6" />
                  </svg>
                </Link>
              </div>
            </Reveal>

            <Reveal delay={0.4}>
              <div className="mt-12 grid max-w-lg grid-cols-3 divide-x divide-line rounded-3xl border border-line bg-panel/50 backdrop-blur">
                {[
                  {
                    v: totalReports ?? 0,
                    l: 'Laporan total',
                  },
                  {
<<<<<<< HEAD
                    v: `${monitoredAreas}+`,
=======
                    v: monitoredAreas ?? 0,
>>>>>>> origin/main
                    l: 'Area terpantau',
                  },
                  {
                    v: riskPredictions ?? 0,
                    l: 'Prediksi Risiko',
                  },
                ].map((s, i) => (
                  <div key={s.l} className="px-5 py-4">
                    <p className="font-display text-2xl font-bold text-emerald-300">
                      <CountUp value={s.v} suffix="+" />
                    </p>

                    <p className="mt-1 text-[11px] leading-snug text-zinc-500">
                      {s.l}
                    </p>
                  </div>
                ))}
              </div>
            </Reveal>
          </div>

          <Reveal delay={0.35} y={40}>
            <HeroCard />
          </Reveal>
        </div>
      </section>

      {/* MARQUEE */}
      <div className="overflow-hidden border-y border-line bg-panel/40 py-4">
        <div className="marquee-track flex w-max whitespace-nowrap">
          {[0, 1].map((dup) => (
            <div
              key={dup}
              className="flex shrink-0 items-center gap-10 pr-10"
              aria-hidden={dup === 1}
            >
              {[
                'Tolak Kekerasan',
                'Laporan Anonim',
                'Rute Aman',
                'Cek Jalur',
                'Kesadaran Sosial',
                'Dari Warga Untuk Warga',
              ].map((t) => (
                <span
                  key={t}
                  className="flex shrink-0 items-center gap-10 text-sm uppercase tracking-[0.3em] text-zinc-600"
                >
                  {t}
                  <span className="text-emerald-500/60">—</span>
                </span>
              ))}
            </div>
          ))}
        </div>
      </div>

      {/* FITUR */}
      <FeaturesSection />

      {/* AGENTS */}
      <AgentsSections />

      {/* CARA KERJA */}
      <HowItWorksSection />

      {/* ETIKA + CTA */}
      <section className="container-x pb-24 pt-15">
        <Reveal>
          <div className="glass-card relative overflow-hidden p-10 text-center sm:p-14">
            <div className="pointer-events-none absolute -top-24 left-1/2 h-64 w-[520px] -translate-x-1/2 rounded-full bg-emerald-500/10 blur-3xl" />

            <h2 className="relative font-display text-3xl font-bold text-white sm:text-4xl">
              Pencegahan, <span className="text-gradient">bukan penghakiman.</span>
            </h2>

            <p className="relative mx-auto mt-4 max-w-2xl text-zinc-400">
              Gardu berfokus pada pencegahan dan keselamatan warga. Tidak ada identifikasi, pelacakan, atau penamaan terduga pelaku. Informasi yang dikumpulkan digunakan untuk membantu memahami kondisi sekitar dan membuat perjalanan lebih aman.
            </p>

            <div className="relative mt-8 flex flex-wrap justify-center gap-4">
              <Link href="/lapor" className="btn-primary">
                Mulai Melapor
              </Link>

              <Link href="/rute" className="btn-ghost">
                Cek Rute Aman
              </Link>
            </div>
          </div>
        </Reveal>
      </section>
    </div>
  );
}