'use client';

import { useRef, useState } from 'react';
import { motion, useReducedMotion } from 'framer-motion';
import { ChevronLeft, ChevronRight, RefreshCw } from 'react-feather';

import { useApiQuery } from '@/hooks/useApiQuery';
import type { PublicReport, PublicReportList, ReportStats } from '@/lib/api-types';
import { formatClockWib, formatCount, formatDateWib, formatNumber } from '@/lib/format';
import { STATUS_HELP, STATUS_LABEL, STATUS_STYLE } from '@/lib/report-status';

const PAGE_SIZE = 12;

function StatCard({ label, value, hint, loading }: { label: string; value: number | undefined; hint?: string; loading: boolean }) {
  return (
    <div className="rounded-2xl border border-line bg-ink/60 px-5 py-4 backdrop-blur-xl">
      <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-zinc-500">{label}</p>
      <p className="mt-1 font-display text-3xl font-bold text-white">
        {loading || value === undefined ? <span className="inline-block h-8 w-14 animate-pulse rounded bg-zinc-800 motion-reduce:animate-none" aria-label="Memuat" /> : formatNumber(value)}
      </p>
      {hint && <p className="mt-1 text-[11px] leading-snug text-zinc-500">{hint}</p>}
    </div>
  );
}

function ReportCard({ report }: { report: PublicReport }) {
  return (
    <li className="rounded-2xl border border-line bg-ink/50 p-5 transition hover:border-emerald-400/30">
      <div className="flex items-start justify-between gap-3">
        <p className="font-display text-base font-semibold tracking-wide text-white">{report.nomor}</p>
        <span
          className={`shrink-0 rounded-full border px-2.5 py-1 text-[11px] font-semibold ${STATUS_STYLE[report.status]}`}
          title={STATUS_HELP[report.status]}
        >
          {STATUS_LABEL[report.status]}
        </span>
      </div>

      <dl className="mt-4 space-y-2 text-sm">
        <div>
          <dt className="sr-only">Wilayah</dt>
          <dd className="text-zinc-200">{report.wilayah}</dd>
        </div>
        <div className="text-xs text-zinc-500">
          <dt className="sr-only">Waktu kejadian</dt>
          <dd>
            Kejadian {formatDateWib(report.occurred_at)}, sekitar pukul {formatClockWib(report.occurred_at)}
          </dd>
        </div>
        <div>
          <dt className="sr-only">Jenis kejadian</dt>
          <dd>
            <span className="inline-block rounded-full border border-line px-2.5 py-0.5 text-[11px] capitalize text-zinc-300">
              {report.jenis}
            </span>
          </dd>
        </div>
      </dl>
    </li>
  );
}

const MARQUEE_COUNT = 12; // laporan terbaru yang bergulir
const MARQUEE_MIN_CARDS_PER_SET = 6; // cukup lebar supaya tidak ada celah kosong saat berputar

/** Ulangi daftar sampai minimal `min` kartu, supaya satu putaran selalu lebih lebar dari layar. */
function fillRow(items: PublicReport[], min: number): PublicReport[] {
  if (items.length === 0) return [];
  const row: PublicReport[] = [];
  while (row.length < min) row.push(...items);
  return row;
}

function MarqueeCard({ report }: { report: PublicReport }) {
  return (
    <article className="flex min-h-[170px] w-[270px] shrink-0 flex-col justify-between overflow-hidden rounded-2xl border border-line bg-[#0b110f]/95 p-5 transition duration-300 hover:border-emerald-400/30 hover:bg-[#101915] sm:w-[320px] sm:p-6">
      <div className="flex items-start justify-between gap-3">
        <span className="inline-flex rounded-full border border-emerald-400/20 bg-emerald-400/[0.07] px-2.5 py-1 text-[10px] font-semibold text-emerald-300">
          {report.nomor}
        </span>

        <span
          className={`inline-flex max-w-[150px] rounded-full border px-2.5 py-1 text-[9px] font-semibold leading-tight ${STATUS_STYLE[report.status]}`}
        >
          {STATUS_LABEL[report.status]}
        </span>
      </div>

      <div className="mt-5">
        <p className="line-clamp-2 break-words text-sm leading-relaxed text-zinc-200">{report.wilayah}</p>

        <div className="mt-4 flex items-center justify-between gap-3 border-t border-white/[0.06] pt-3">
          <span className="min-w-0 truncate text-[10px] text-zinc-500">
            {formatDateWib(report.occurred_at)}, sekitar {formatClockWib(report.occurred_at)}
          </span>
          <span className="shrink-0 rounded-full border border-line px-2.5 py-0.5 text-[10px] capitalize text-zinc-300">
            {report.jenis}
          </span>
        </div>
      </div>
    </article>
  );
}

function MarqueeRow({ items, direction, label }: { items: PublicReport[]; direction: 'left' | 'right'; label: string }) {
  const reduceMotion = useReducedMotion();
  const set = fillRow(items, MARQUEE_MIN_CARDS_PER_SET);

  if (set.length === 0) return null;

  const fade = 'pointer-events-none absolute inset-y-0 z-10 w-8 from-ink to-transparent sm:w-20';

  // Gerak dimatikan bila pengguna meminta: baris dibuat bisa digulir manual.
  if (reduceMotion) {
    return (
      <div className="relative py-2" role="list" aria-label={label}>
        <div className="flex gap-4 overflow-x-auto pb-2">
          {items.map((report) => (
            <div role="listitem" key={report.nomor}>
              <MarqueeCard report={report} />
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="relative overflow-hidden py-2" aria-label={label}>
      <div className={`${fade} left-0 bg-gradient-to-r`} />
      <div className={`${fade} right-0 bg-gradient-to-l`} />

      <motion.div
        className="flex w-max gap-4 pr-4"
        animate={{ x: direction === 'left' ? ['0%', '-50%'] : ['-50%', '0%'] }}
        transition={{ duration: Math.max(60, set.length * 12), ease: 'linear', repeat: Infinity }}
        style={{ willChange: 'transform' }}
      >
        {[0, 1].map((copy) =>
          set.map((report, index) => (
            // Salinan kedua hanya untuk perulangan visual: disembunyikan dari pembaca layar.
            <div key={`${copy}-${index}-${report.nomor}`} aria-hidden={copy === 1}>
              <MarqueeCard report={report} />
            </div>
          )),
        )}
      </motion.div>
    </div>
  );
}

/** Dua baris laporan terbaru yang bergulir berlawanan arah (hanya data aman untuk publik). */
function ReportMarquee({ items, loading }: { items: PublicReport[]; loading: boolean }) {
  if (loading || items.length === 0) return null;

  const first = items.filter((_, index) => index % 2 === 0);
  const second = items.filter((_, index) => index % 2 === 1);

  return (
    <section className="mt-2" aria-labelledby="pantauan-laporan">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.25em] text-emerald-400">Laporan masyarakat</p>
          <h2 id="pantauan-laporan" className="mt-1 font-display text-lg font-semibold text-white">
            Pantauan laporan terkini
          </h2>
        </div>

        <span className="flex items-center gap-2 text-[10px] text-zinc-500">
          <span className="relative flex h-2 w-2" aria-hidden="true">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-50 motion-reduce:animate-none" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-400" />
          </span>
          Ringkasan laporan
        </span>
      </div>

      <MarqueeRow items={first} direction="left" label="Laporan terbaru, baris pertama" />
      {second.length > 0 && <MarqueeRow items={second} direction="right" label="Laporan terbaru, baris kedua" />}
    </section>
  );
}

/** Histori laporan publik (anonim) + statistik, dengan paginasi dari backend. */
export default function ReportHistory() {
  const [page, setPage] = useState(0);
  const listRef = useRef<HTMLDivElement>(null);

  const stats = useApiQuery<ReportStats>('/reports/stats', {}, 'Statistik belum dapat dimuat.');
  const list = useApiQuery<PublicReportList>(
    '/reports/public',
    { limit: PAGE_SIZE, offset: page * PAGE_SIZE },
    'Daftar laporan belum dapat dimuat.',
  );

  // Satu permintaan bersama untuk marquee (12 laporan terbaru); sama dengan halaman pertama daftar bila PAGE_SIZE sama.
  const recent = useApiQuery<PublicReportList>(
    '/reports/public',
    { limit: MARQUEE_COUNT, offset: 0 },
    'Laporan terbaru belum dapat dimuat.',
  );

  const total = list.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const items = list.data?.items ?? [];
  const byStatus = stats.data?.reports_by_status;
  const hidden = byStatus ? byStatus.ditandai_duplikat + byStatus.ditandai_hoaks : undefined;

  function goTo(next: number) {
    setPage(next);
    listRef.current?.scrollIntoView({
      behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
      block: 'start',
    });
  }

  return (
    <div className="space-y-8">
      <section aria-label="Statistik laporan">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatCard label="Total laporan" value={stats.data?.total_reports} loading={stats.loading} />
          <StatCard label="Terverifikasi" value={byStatus?.terverifikasi} loading={stats.loading} />
          <StatCard label="Menunggu verifikasi" value={byStatus?.menunggu_verifikasi} loading={stats.loading} />
          <StatCard
            label="Insiden terverifikasi"
            value={stats.data?.verified_incidents}
            loading={stats.loading}
            hint="Kejadian yang dikuatkan beberapa laporan"
          />
        </div>

        {stats.error && (
          <p className="mt-3 text-xs text-amber-300" role="alert">
            {stats.error}{' '}
            <button type="button" onClick={stats.retry} className="font-semibold underline underline-offset-2">
              Muat ulang
            </button>
          </p>
        )}
      </section>

      <div className="flex items-start gap-3 rounded-xl border border-line bg-ink/40 px-4 py-3">
        <span className="text-emerald-400" aria-hidden="true">ⓘ</span>
        <p className="text-xs leading-relaxed text-zinc-500">
          Daftar menampilkan laporan terbaru yang <strong className="text-zinc-400">menunggu verifikasi</strong> atau{' '}
          <strong className="text-zinc-400">terverifikasi</strong>, tanpa isi laporan, jalan, atau koordinat demi privasi
          pelapor. Laporan yang ditandai duplikat atau hoaks tidak ditampilkan dan hanya dihitung secara agregat
          {hidden !== undefined ? ` (${formatCount(hidden, 'laporan')})` : ''}. Data diperbarui sekitar tiap menit; laporan
          yang baru dikirim mungkin belum langsung tampil.
        </p>
      </div>

      <ReportMarquee items={recent.data?.items ?? []} loading={recent.loading} />

      <section ref={listRef} className="scroll-mt-28" aria-labelledby="daftar-laporan" aria-busy={list.loading}>
        <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
          <h2 id="daftar-laporan" className="font-display text-lg font-semibold text-white">
            Laporan terbaru
          </h2>

          {!list.loading && !list.error && total > 0 && (
            <p className="text-xs text-zinc-500" aria-live="polite">
              Menampilkan {page * PAGE_SIZE + 1}-{page * PAGE_SIZE + items.length} dari {formatNumber(total)} laporan
            </p>
          )}
        </div>

        {list.loading && (
          <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3" aria-hidden="true">
            {Array.from({ length: 6 }).map((_, index) => (
              <li key={index} className="h-36 animate-pulse rounded-2xl border border-line bg-ink/50 motion-reduce:animate-none" />
            ))}
          </ul>
        )}

        {list.error && (
          <div className="rounded-2xl border border-red-400/20 bg-red-400/5 p-8 text-center" role="alert">
            <p className="text-sm text-red-200">{list.error}</p>
            <button type="button" onClick={list.retry} className="btn-ghost mt-5 !px-5 !py-2">
              <RefreshCw size={14} aria-hidden="true" />
              Coba lagi
            </button>
          </div>
        )}

        {!list.loading && !list.error && items.length === 0 && (
          <div className="rounded-2xl border border-line bg-ink/40 p-10 text-center">
            <p className="font-display text-lg font-semibold text-white">
              {page > 0 ? 'Halaman ini kosong' : 'Belum ada laporan yang dapat ditampilkan'}
            </p>
            <p className="mt-2 text-sm text-zinc-500">
              {page > 0 ? 'Kembali ke halaman sebelumnya.' : 'Laporan yang masuk akan muncul di sini setelah diproses.'}
            </p>
            {page > 0 && (
              <button type="button" onClick={() => goTo(0)} className="btn-ghost mt-5 !px-5 !py-2">
                Ke halaman pertama
              </button>
            )}
          </div>
        )}

        {!list.loading && !list.error && items.length > 0 && (
          <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {items.map((report) => (
              <ReportCard key={report.nomor} report={report} />
            ))}
          </ul>
        )}

        {!list.error && total > PAGE_SIZE && (
          <nav className="mt-6 flex items-center justify-between gap-3" aria-label="Paginasi laporan">
            <button
              type="button"
              onClick={() => goTo(page - 1)}
              disabled={page === 0 || list.loading}
              className="btn-ghost !px-4 !py-2 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <ChevronLeft size={16} aria-hidden="true" />
              Sebelumnya
            </button>

            <p className="text-xs text-zinc-500">
              Halaman {page + 1} dari {pages}
            </p>

            <button
              type="button"
              onClick={() => goTo(page + 1)}
              disabled={page + 1 >= pages || list.loading}
              className="btn-ghost !px-4 !py-2 disabled:cursor-not-allowed disabled:opacity-40"
            >
              Berikutnya
              <ChevronRight size={16} aria-hidden="true" />
            </button>
          </nav>
        )}
      </section>
    </div>
  );
}
