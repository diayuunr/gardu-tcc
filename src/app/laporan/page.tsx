
'use client';

import { useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import Reveal from '@/components/Reveal';
import { supabase } from '@/lib/supabase';
import { ArrowRight, ArrowUpRight } from 'react-feather';

type ReportStatus =
  | 'menunggu_verifikasi'
  | 'terverifikasi'
  | 'ditandai_duplikat'
  | 'ditandai_hoaks';

type ReportHistory = {
  id: string;
  description: string;
  location_text: string | null;
  latitude: number | null;
  longitude: number | null;
  occurred_at: string;
  status: ReportStatus | string | null;
};

type NewsArticle = {
  title: string;
  date: string;
  source: string;
  category: string;
  excerpt: string;
  image: string;
  imageAlt: string;
  imageNote: string;
  url: string;
};

const REPORTS_PER_PAGE = 7;

const STATUS_STYLE: Record<string, string> = {
  menunggu_verifikasi:
    'border-amber-400/30 bg-amber-400/10 text-amber-300',
  terverifikasi:
    'border-emerald-400/30 bg-emerald-400/10 text-emerald-300',
  ditandai_duplikat:
    'border-sky-400/30 bg-sky-400/10 text-sky-300',
  ditandai_hoaks:
    'border-red-400/30 bg-red-400/10 text-red-300',
};

const STATUS_LABEL: Record<string, string> = {
  menunggu_verifikasi: 'Menunggu verifikasi',
  terverifikasi: 'Terverifikasi',
  ditandai_duplikat: 'Duplikat',
  ditandai_hoaks: 'Hoaks',
};

/*
 * Berita pilihan untuk section berita GARDU.
 * URL artikel menuju sumber asli.
 * Beberapa gambar merupakan foto ilustrasi/arsip,
 * bukan foto yang diklaim berasal dari artikel terbaru.
 */
const NEWS_ARTICLES: NewsArticle[] = [
  {
    title:
      'Viral Korban Klitih di Pleret Bantul Terluka hingga Dioperasi, Polisi Selidiki',
    date: '21 Oktober 2026',
    source: 'detikJogja',
    category: 'Kejahatan Jalanan',
    excerpt:
      'Polisi menyelidiki dugaan kejahatan jalanan di Pleret, Bantul, setelah seorang pria dilaporkan mengalami luka serius. Petugas telah mendatangi lokasi dan meminta keterangan saksi untuk mendalami kejadian.',
    image:
      'https://awsimages.detik.net.id/community/media/visual/2026/02/10/viral-di-bantul-1770705745676_169.jpeg?q=90&w=700',
    imageAlt: 'Ilustrasi penanganan kejadian di wilayah Bantul',
    imageNote: 'Foto ilustrasi/arsip',
    url:
      'https://www.detik.com/jogja/berita/d-8718000/viral-korban-klitih-di-pleret-bantul-terluka-hingga-dioperasi-polisi-selidiki',
  },
  {
    title:
      'Klitih Belum Hilang, JPW Desak Polisi Perketat Pengawasan Malam di Bantul',
    date: '19 Oktober 2026',
    source: 'Disway Jogja',
    category: 'Pencegahan',
    excerpt:
      'Jogja Police Watch menyoroti pentingnya evaluasi pencegahan kejahatan jalanan. Pengawasan pada malam hingga dini hari, pendekatan keluarga, dan pelibatan masyarakat menjadi bagian dari upaya menjaga keamanan.',
    image:
      'https://assets.pikiran-rakyat.com/crop/382x127%3A1242x660/720x0/webp/photo/2025/07/26/3351686213.jpg',
    imageAlt: 'Rekaman CCTV terkait insiden kejahatan jalanan',
    imageNote: 'Foto ilustrasi/arsip',
    url:
      'https://jogja.disway.id/daerah/read/702339/klitih-belum-hilang-jpw-desak-polisi-perketat-pengawasan-malam-di-bantul',
  },
  {
    title:
      'Belasan Remaja Diamankan Polisi Usai Dihajar Massa di Bantul',
    date: '5 Oktober 2026',
    source: 'detikJogja',
    category: 'Proses Hukum',
    excerpt:
      'Sebanyak 13 remaja diamankan untuk pemeriksaan setelah insiden di Jalan Samas, Sanden, Bantul. Polisi meminta masyarakat tidak terburu-buru menyimpulkan keterlibatan setiap orang sebelum penyelidikan selesai.',
    image:
      'https://cloud.jpnn.com/photo/arsip/normal/2021/11/30/remaja-diduga-klitih-diamankan-polres-bantul-pada-senin-2911-wc7y.jpg',
    imageAlt: 'Dokumentasi arsip penanganan kasus kejahatan jalanan',
    imageNote: 'Foto arsip, bukan foto kejadian ini',
    url:
      'https://www.detik.com/jogja/berita/d-8692323/belasan-remaja-diamankan-polisi-usai-dihajar-massa-di-bantul',
  },
];

export default function LaporanHistoryPage() {
  const [reports, setReports] = useState<ReportHistory[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [currentPage, setCurrentPage] = useState(1);

  // LOAD REPORTS — logic Supabase tetap.
  useEffect(() => {
    async function loadReports() {
      try {
        setLoading(true);
        setError('');

        if (!supabase) {
          throw new Error('Koneksi Supabase tidak tersedia.');
        }

        const { data, error: supabaseError } = await supabase
          .from('reports')
          .select(
            'id, description, location_text, latitude, longitude, occurred_at, status',
          )
          .order('occurred_at', { ascending: false });

        if (supabaseError) {
          console.error('SUPABASE REPORT ERROR:', supabaseError);
          throw supabaseError;
        }

        setReports((data as ReportHistory[]) ?? []);
      } catch (err) {
        console.error('Gagal mengambil histori laporan:', err);
        setError('Histori laporan belum dapat dimuat.');
      } finally {
        setLoading(false);
      }
    }

    loadReports();
  }, []);

  // Pagination tetap digunakan untuk menentukan laporan marquee.
  const totalPages = Math.ceil(reports.length / REPORTS_PER_PAGE);

  const currentReports = useMemo(() => {
    const startIndex = (currentPage - 1) * REPORTS_PER_PAGE;
    return reports.slice(startIndex, startIndex + REPORTS_PER_PAGE);
  }, [reports, currentPage]);

  function getPageNumbers() {
    const pages: (number | '...')[] = [];

    if (totalPages <= 5) {
      for (let i = 1; i <= totalPages; i++) {
        pages.push(i);
      }

      return pages;
    }

    pages.push(1);

    if (currentPage > 3) pages.push('...');

    const start = Math.max(2, currentPage - 1);
    const end = Math.min(totalPages - 1, currentPage + 1);

    for (let i = start; i <= end; i++) {
      pages.push(i);
    }

    if (currentPage < totalPages - 2) pages.push('...');

    pages.push(totalPages);

    return pages;
  }

const midpoint = Math.ceil(reports.length / 2);

const firstRow = reports.slice(0, midpoint);
const secondRow = reports.slice(midpoint);

  return (
    <main className="min-h-screen overflow-hidden pb-24 pt-32">
      {/* HEADER */}
      <div className="container-x">
        <Reveal>
          <div className="flex flex-wrap items-end justify-between gap-5">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.3em] text-emerald-400">
                Transparansi
              </p>

              <h1 className="mt-3 font-display text-2xl font-bold tracking-tight text-white sm:text-5xl">
                Histori Laporan
              </h1>

              <p className="mt-3 max-w-xl text-base leading-normal text-zinc-500">
                Pantau laporan kejadian yang masuk ke sistem GARDU,
                lengkap dengan status dan informasi lokasinya.
              </p>
            </div>

            {!loading && !error && (
              <div className="rounded-2xl border border-line bg-ink/60 px-5 py-4 backdrop-blur-xl">
                <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-zinc-500">
                  Total laporan
                </p>

                <p className="mt-1 font-display text-3xl font-bold text-white">
                  {reports.length}
                </p>
              </div>
            )}
          </div>
        </Reveal>

        <Reveal delay={0.1}>
          <div className="mt-7 flex items-start gap-3 rounded-xl border border-line bg-ink/40 px-4 py-3">
            <span className="mt-[-0.5] text-emerald-400">ⓘ</span>

            <p className="text-xs mt-0.5 leading-relaxed text-zinc-500">
              Laporan ditampilkan dari yang terbaru. Status merupakan
              informasi sistem dan tidak dapat diubah melalui halaman ini.
            </p>
          </div>
        </Reveal>
      </div>

      {/* LOADING */}
      {loading && (
        <div className="container-x mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, index) => (
            <div
              key={index}
              className="animate-pulse rounded-2xl border border-line bg-ink/50 p-5"
            >
              <div className="h-4 w-28 rounded bg-zinc-800" />
              <div className="mt-5 h-3 w-full rounded bg-zinc-800" />
              <div className="mt-2 h-3 w-4/5 rounded bg-zinc-800" />
              <div className="mt-6 h-3 w-32 rounded bg-zinc-800" />
            </div>
          ))}
        </div>
      )}

      {/* ERROR */}
      {!loading && error && (
        <div className="container-x mt-8">
          <div className="rounded-2xl border border-red-400/20 bg-red-400/5 p-8 text-center">
            <p className="text-sm text-red-300">{error}</p>

            <button
              type="button"
              onClick={() => window.location.reload()}
              className="mt-5 rounded-xl bg-emerald-400 px-5 py-2.5 text-sm font-semibold text-emerald-950 transition hover:bg-emerald-300"
            >
              Coba lagi
            </button>
          </div>
        </div>
      )}

      {/* EMPTY */}
      {!loading && !error && reports.length === 0 && (
        <div className="container-x mt-8">
          <div className="rounded-2xl border border-line bg-ink/40 p-10 text-center">
            <p className="font-display text-lg font-semibold text-white">
              Belum ada laporan
            </p>

            <p className="mt-2 text-sm text-zinc-500">
              Belum ada laporan yang masuk ke dalam sistem.
            </p>
          </div>
        </div>
      )}

      {/* REPORT MARQUEE */}
      {!loading && !error && reports.length > 0 && (
        <section className="mt-10">
          <div className="container-x mb-5 flex items-center justify-between">
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.25em] text-emerald-400">
                Laporan masyarakat
              </p>

              <h2 className="mt-1 font-display text-lg font-semibold text-white">
                Pantauan laporan terkini
              </h2>
            </div>

            <span className="flex items-center gap-2 text-[10px] text-zinc-500">
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-50" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-400" />
              </span>
              Ringkasan laporan
            </span>
          </div>

          {/* BARIS 1 — KIRI */}
          {firstRow.length > 0 && (
            <div className="group/marquee relative overflow-hidden py-2">
              <div className="pointer-events-none absolute inset-y-0 left-0 z-10 w-8 bg-gradient-to-r from-[#080d0b] to-transparent sm:w-20" />
              <div className="pointer-events-none absolute inset-y-0 right-0 z-10 w-8 bg-gradient-to-l from-[#080d0b] to-transparent sm:w-20" />

              <motion.div
                className="flex w-max gap-4 pr-4"
                animate={{ x: ['0%', '-50%'] }}
                transition={{
                  duration: Math.max(60, firstRow.length * 30),
                  ease: 'linear',
                  repeat: Infinity,
                }}
                style={{ willChange: 'transform' }}
              >
                {[0, 1].map((copy) =>
                  firstRow.map((report) => (
                    <ReportCard
                      key={`${copy}-${report.id}`}
                      report={report}
                      number={reports.findIndex((item) => item.id === report.id) + 1}
                      total={reports.length}
                    />
                  )),
                )}
              </motion.div>
            </div>
          )}

          {/* BARIS 2 — KANAN */}
          {secondRow.length > 0 && (
            <div className="group/marquee relative mt-3 overflow-hidden py-2">
              <div className="pointer-events-none absolute inset-y-0 left-0 z-10 w-8 bg-gradient-to-r from-[#080d0b] to-transparent sm:w-20" />
              <div className="pointer-events-none absolute inset-y-0 right-0 z-10 w-8 bg-gradient-to-l from-[#080d0b] to-transparent sm:w-20" />

              <motion.div
                className="flex w-max gap-4 pr-4"
                animate={{ x: ['-50%', '0%'] }}
                transition={{
                  duration: Math.max(60, secondRow.length * 30),
                  ease: 'linear',
                  repeat: Infinity,
                }}
                style={{ willChange: 'transform' }}
              >
                {[0, 1].map((copy) =>
                  secondRow.map((report) => (
                    <ReportCard
                      key={`${copy}-${report.id}`}
                      report={report}
                      number={reports.findIndex((item) => item.id === report.id) + 1}
                      total={reports.length}
                    />
                  )),
                )}
              </motion.div>
            </div>
          )}

        </section>
      )}

      {/* ================
          BERITA TERKINI
      ====================*/}

      <section className="container-x mt-20">
        <Reveal>
          <div className="flex flex-wrap items-end justify-between gap-4 border-b border-line pb-6">
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.3em] text-emerald-400">
                News &amp; Updates
              </p>

              <h2 className="mt-3 font-display text-3xl font-bold tracking-tight text-white sm:text-4xl">
                Berita Terkini
              </h2>

              <p className="mt-3 max-w-xl text-sm leading-relaxed text-zinc-500">
                Ikuti perkembangan informasi mengenai klitih dan
                kejahatan jalanan di Yogyakarta dan sekitarnya.
              </p>
            </div>

            <a
              href="https://www.detik.com/tag/klitih"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 text-xs font-semibold text-emerald-300 transition hover:text-emerald-200"
            >
              Jelajahi berita lainnya
              <span aria-hidden="true"><ArrowUpRight className="h-4 w-4" /></span>
            </a>
          </div>
        </Reveal>

        <div className="mt-7 grid gap-5 md:grid-cols-2 lg:grid-cols-3">
          {NEWS_ARTICLES.map((article, index) => (
            <Reveal key={article.url} delay={index * 0.08}>
              <a
                href={article.url}
                target="_blank"
                rel="noopener noreferrer"
                aria-label={`Baca artikel: ${article.title}`}
                className="group flex h-full flex-col overflow-hidden rounded-2xl border border-line bg-ink/40 transition duration-300 hover:-translate-y-1 hover:border-emerald-400/30 hover:bg-ink/70"
              >
                {/* ARTICLE IMAGE */}
                <div className="relative aspect-[16/10] overflow-hidden bg-zinc-900">
                  <img
                    src={article.image}
                    alt={article.imageAlt}
                    loading="lazy"
                    className="h-full w-full object-cover transition duration-500 group-hover:scale-[1.04]"
                    onError={(event) => {
                      event.currentTarget.style.display = 'none';
                    }}
                  />

                  <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-black/75 via-black/10 to-transparent" />

                  <span className="absolute left-4 top-4 rounded-full border border-white/15 bg-black/50 px-3 py-1.5 text-[9px] font-semibold uppercase tracking-wider text-white backdrop-blur-md">
                    {article.category}
                  </span>

                  <span className="absolute bottom-3 left-4 text-[9px] text-white/70">
                    {article.imageNote}
                  </span>

                  <span className="absolute bottom-3 right-4 flex h-8 w-8 items-center justify-center rounded-full border border-white/20 bg-black/40 text-white transition group-hover:border-emerald-300 group-hover:bg-emerald-400 group-hover:text-emerald-950">
                    <ArrowUpRight className="h-5 w-5" />
                  </span>
                </div>

                {/* ARTICLE CONTENT */}
                <div className="flex flex-1 flex-col p-5 sm:p-6">
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[10px] text-zinc-500">
                    <span className="font-semibold text-emerald-300">
                      {article.source}
                    </span>
                    <span className="text-zinc-700">•</span>
                    <span>{article.date}</span>
                  </div>

                  <h3 className="mt-4 line-clamp-3 font-display text-lg font-semibold leading-snug text-white transition group-hover:text-emerald-200">
                    {article.title}
                  </h3>

                  <p className="mt-3 line-clamp-4 flex-1 text-xs leading-relaxed text-zinc-400">
                    {article.excerpt}
                  </p>

                  <div className="mt-6 flex items-center justify-between border-t border-white/[0.06] pt-4">
                    <span className="text-[10px] text-zinc-500">
                      Baca artikel lengkap
                    </span>

                    <span className="text-xs font-semibold text-emerald-300 transition group-hover:translate-x-1">
                      <ArrowRight className="h-4 w-4" />
                    </span>
                  </div>
                </div>
              </a>
            </Reveal>
          ))}
        </div>

        {/* EDITORIAL NOTE */}
        <div className="mt-6 flex items-start gap-3 rounded-xl border border-line bg-ink/30 px-4 py-3">
          <span className="mt-[-0.5] text-emerald-400">ⓘ</span>

          <p className="text-[11px] mt-0.5 leading-relaxed text-zinc-500">
            Berita berasal dari media eksternal. Informasi dugaan
            tindak pidana harus dipahami berdasarkan keterangan dan
            proses penyelidikan resmi. GARDU tidak menyatakan seseorang
            bersalah berdasarkan pemberitaan semata.
          </p>
        </div>
      </section>
    </main>
  );
}

/* =========================================================
   REPORT CARD
========================================================= */

function ReportCard({
  report,
  number,
  total,
}: {
  report: ReportHistory;
  number: number;
  total: number;
}) {
  const status = report.status ?? 'menunggu_verifikasi';

  return (
    <article className="group/card flex min-h-[205px] w-[290px] shrink-0 flex-col justify-between overflow-hidden rounded-2xl border border-line bg-[#0b110f]/95 p-5 transition duration-300 hover:border-emerald-400/30 hover:bg-[#101915] sm:w-[340px] sm:p-6">
      <div>
        <div className="flex items-start justify-between gap-3">
          <span className="inline-flex rounded-full border border-emerald-400/20 bg-emerald-400/[0.07] px-2.5 py-1 text-[10px] font-semibold text-emerald-300">
            LAPORAN #{total - number + 1}
          </span>

          <span
            className={`inline-flex max-w-[150px] rounded-full border px-2.5 py-1 text-[9px] font-semibold leading-tight ${
              STATUS_STYLE[status] ??
              'border-zinc-700 bg-zinc-800 text-zinc-400'
            }`}
          >
            {STATUS_LABEL[status] ?? status.replace(/_/g, ' ')}
          </span>
        </div>

        <p className="mt-5 line-clamp-3 whitespace-normal break-words text-sm leading-relaxed text-zinc-200">
          {report.description}
        </p>
      </div>

      <div className="mt-5 border-t border-white/[0.06] pt-4">
        <div className="flex items-start gap-2 text-xs text-zinc-400">
          <span className="mt-[-0.5] text-emerald-400">●</span>

          <span className="min-w-0 break-words">
            {report.location_text || 'Lokasi tidak tersedia'}
          </span>
        </div>

        {report.latitude !== null && report.longitude !== null && (
          <p className="mt-2 pl-4 text-[10px] tabular-nums text-zinc-600">
            {report.latitude.toFixed(4)}, {report.longitude.toFixed(4)}
          </p>
        )}

        <p className="mt-3 text-[10px] leading-relaxed text-zinc-500">
          {formatDate(report.occurred_at)}
        </p>
      </div>
    </article>
  );
}

/* =========================================================
   FORMAT TANGGAL
========================================================= */

function formatDate(value: string): string {
  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return 'Waktu tidak tersedia';
  }

  return date.toLocaleString('id-ID', {
    day: '2-digit',
    month: 'long',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}
