'use client';

import { useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';

import Reveal from '@/components/Reveal';
import { supabase } from '@/lib/supabase';

type ReportStatus =
  | 'menunggu_verifikasi'
  | 'terverifikasi'
  | 'duplikat'
  | 'hoaks';

type ReportHistory = {
  id: string;
  description: string;
  location: string | null;
  lat: number | null;
  lng: number | null;
  reported_at: string;
  status: ReportStatus | string | null;
};

const REPORTS_PER_PAGE = 7;

const STATUS_STYLE: Record<string, string> = {
  menunggu_verifikasi:
    'border-amber-400/30 bg-amber-400/10 text-amber-300',

  terverifikasi:
    'border-emerald-400/30 bg-emerald-400/10 text-emerald-300',

  duplikat:
    'border-sky-400/30 bg-sky-400/10 text-sky-300',

  hoaks:
    'border-red-400/30 bg-red-400/10 text-red-300',
};

const STATUS_LABEL: Record<string, string> = {
  menunggu_verifikasi: 'Menunggu verifikasi',
  terverifikasi: 'Terverifikasi',
  duplikat: 'Duplikat',
  hoaks: 'Hoaks',
};

export default function LaporanHistoryPage() {
  const [reports, setReports] = useState<ReportHistory[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const [currentPage, setCurrentPage] = useState(1);

  /*
   * =========================================================
   * LOAD REPORTS
   * =========================================================
   */

  useEffect(() => {
    async function loadReports() {
      try {
        setLoading(true);
        setError('');

        if (!supabase) {
          throw new Error(
            'Koneksi Supabase tidak tersedia.',
          );
        }

        const { data, error: supabaseError } =
          await supabase
            .from('reports')
            .select(
              'id, description, location, lat, lng, reported_at, status',
            )
            .order('reported_at', {
              ascending: false,
            });

        if (supabaseError) {
          console.error(
            'SUPABASE REPORT ERROR:',
            supabaseError,
          );

          throw supabaseError;
        }

        console.log(
          'HISTORI LAPORAN:',
          data,
        );

        setReports(
          (data as ReportHistory[]) ?? [],
        );
      } catch (err) {
        console.error(
          'Gagal mengambil histori laporan:',
          err,
        );

        setError(
          'Histori laporan belum dapat dimuat.',
        );
      } finally {
        setLoading(false);
      }
    }

    loadReports();
  }, []);

  /*
   * =========================================================
   * PAGINATION
   * =========================================================
   */

  const totalPages = Math.ceil(
    reports.length / REPORTS_PER_PAGE,
  );

  const currentReports = useMemo(() => {
    const startIndex =
      (currentPage - 1) * REPORTS_PER_PAGE;

    const endIndex =
      startIndex + REPORTS_PER_PAGE;

    return reports.slice(
      startIndex,
      endIndex,
    );
  }, [reports, currentPage]);

  /*
   * =========================================================
   * HANDLE PAGE
   * =========================================================
   */

  function goToPage(page: number) {
    if (
      page < 1 ||
      page > totalPages
    ) {
      return;
    }

    setCurrentPage(page);

    window.scrollTo({
      top: 0,
      behavior: 'smooth',
    });
  }

  /*
   * =========================================================
   * PAGE NUMBERS
   * =========================================================
   */

  function getPageNumbers() {
    const pages: (
      number | '...'
    )[] = [];

    if (totalPages <= 5) {
      for (
        let i = 1;
        i <= totalPages;
        i++
      ) {
        pages.push(i);
      }

      return pages;
    }

    pages.push(1);

    if (currentPage > 3) {
      pages.push('...');
    }

    const start = Math.max(
      2,
      currentPage - 1,
    );

    const end = Math.min(
      totalPages - 1,
      currentPage + 1,
    );

    for (
      let i = start;
      i <= end;
      i++
    ) {
      pages.push(i);
    }

    if (
      currentPage <
      totalPages - 2
    ) {
      pages.push('...');
    }

    pages.push(totalPages);

    return pages;
  }

  /*
   * =========================================================
   * RENDER
   * =========================================================
   */

  return (
    <div className="container-x min-h-screen pb-24 pt-32">
      {/* =====================================================
          HEADER
      ====================================================== */}

      <Reveal>
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.3em] text-emerald-400">
              Transparansi
            </p>

            <h1 className="mt-3 font-display text-4xl font-bold text-white">
              Histori Laporan
            </h1>

            <p className="mt-2 max-w-2xl text-zinc-500">
              Riwayat laporan kejadian yang
              telah masuk ke dalam sistem.
            </p>
          </div>

          {!loading && !error && (
            <div className="glass-card px-5 py-3 text-right">
              <p className="text-[10px] uppercase tracking-widest text-zinc-500">
                Total laporan
              </p>

              <p className="mt-1 font-display text-2xl font-bold text-white">
                {reports.length}
              </p>
            </div>
          )}
        </div>
      </Reveal>

      {/* =====================================================
          INFO
      ====================================================== */}

      <Reveal delay={0.1}>
        <div className="mt-8 rounded-2xl border border-line bg-ink/40 p-4">
          <p className="text-xs leading-relaxed text-zinc-500">
            Menampilkan laporan terbaru yang
            masuk ke dalam sistem. Status laporan
            ditampilkan sebagai informasi dan tidak
            dapat diubah dari halaman ini.
          </p>
        </div>
      </Reveal>

      {/* =====================================================
          LOADING
      ====================================================== */}

      {loading && (
        <div className="mt-6 space-y-4">
          {Array.from({
            length: 4,
          }).map((_, index) => (
            <motion.div
              key={index}
              className="glass-card p-6"
              initial={{
                opacity: 0,
              }}
              animate={{
                opacity: 1,
              }}
            >
              <div className="animate-pulse">
                <div className="flex justify-between">
                  <div className="h-6 w-32 rounded-full bg-zinc-800" />

                  <div className="h-4 w-32 rounded bg-zinc-800" />
                </div>

                <div className="mt-5 h-3 w-full rounded bg-zinc-800" />

                <div className="mt-2 h-3 w-4/5 rounded bg-zinc-800" />

                <div className="mt-5 h-3 w-52 rounded bg-zinc-800" />
              </div>
            </motion.div>
          ))}
        </div>
      )}

      {/* =====================================================
          ERROR
      ====================================================== */}

      {!loading && error && (
        <Reveal delay={0.15}>
          <div className="glass-card mt-6 p-8 text-center">
            <p className="text-sm text-red-300">
              {error}
            </p>

            <button
              type="button"
              onClick={() =>
                window.location.reload()
              }
              className="btn-primary mt-5"
            >
              Coba lagi
            </button>
          </div>
        </Reveal>
      )}

      {/* =====================================================
          EMPTY
      ====================================================== */}

      {!loading &&
        !error &&
        reports.length === 0 && (
          <Reveal delay={0.15}>
            <div className="glass-card mt-6 p-10 text-center">
              <p className="font-display text-lg font-semibold text-white">
                Belum ada laporan
              </p>

              <p className="mt-2 text-sm text-zinc-500">
                Belum ada laporan yang masuk
                ke dalam sistem.
              </p>
            </div>
          </Reveal>
        )}

      {/* =====================================================
          REPORT LIST
      ====================================================== */}

      {!loading &&
        !error &&
        reports.length > 0 && (
          <>
            <div className="mt-6 space-y-4">
              {currentReports.map(
                (report, index) => {
                  const globalIndex =
                    (currentPage - 1) *
                      REPORTS_PER_PAGE +
                    index;

                  const status =
                    report.status ??
                    'menunggu_verifikasi';

                  return (
                    <Reveal
                      key={report.id}
                      delay={Math.min(
                        index * 0.03,
                        0.3,
                      )}
                    >
                      <motion.article
                        layout
                        whileHover={{
                          y: -2,
                        }}
                        transition={{
                          duration: 0.2,
                        }}
                        className="glass-card p-6"
                      >
                        <div className="flex flex-col gap-4">
                          {/* HEADER */}
                          <div className="flex flex-wrap items-center justify-between gap-3">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="rounded-full border border-emerald-400/30 bg-emerald-400/10 px-3 py-1 text-[11px] font-semibold text-emerald-300">
                                Laporan #
                                {reports.length -
                                  globalIndex}
                              </span>

                              <span
                                className={`rounded-full border px-3 py-1 text-[11px] font-semibold ${
                                  STATUS_STYLE[
                                    status
                                  ] ??
                                  'border-zinc-700 bg-zinc-800 text-zinc-400'
                                }`}
                              >
                                {STATUS_LABEL[
                                  status
                                ] ??
                                  status.replace(
                                    /_/g,
                                    ' ',
                                  )}
                              </span>
                            </div>

                            <span className="text-xs text-zinc-600">
                              {formatDate(
                                report.reported_at,
                              )}
                            </span>
                          </div>

                          {/* DESCRIPTION */}
                          <p className="max-w-3xl text-sm leading-relaxed text-zinc-200">
                            {report.description}
                          </p>

                          {/* LOCATION */}
                          <div className="flex flex-wrap items-center gap-3 text-xs text-zinc-500">
                            <span className="inline-flex items-center gap-2">
                              <span className="text-emerald-400">
                                ●
                              </span>

                              <span>
                                {report.location ||
                                  'Lokasi tidak tersedia'}
                              </span>
                            </span>

                            {report.lat !==
                              null &&
                              report.lng !==
                                null && (
                                <>
                                  <span className="text-zinc-700">
                                    •
                                  </span>

                                  <span>
                                    {report.lat.toFixed(
                                      4,
                                    )}
                                    ,{' '}
                                    {report.lng.toFixed(
                                      4,
                                    )}
                                  </span>
                                </>
                              )}
                          </div>
                        </div>
                      </motion.article>
                    </Reveal>
                  );
                },
              )}
            </div>

            {/* =================================================
                PAGINATION
            ================================================== */}

            {totalPages > 1 && (
              <Reveal delay={0.15}>
                <div className="mt-8 flex flex-wrap items-center justify-center gap-2">
                  {/* PREVIOUS */}
                  <button
                    type="button"
                    onClick={() =>
                      goToPage(
                        currentPage - 1,
                      )
                    }
                    disabled={
                      currentPage === 1
                    }
                    className={`rounded-xl border px-3 py-2 text-xs font-semibold transition ${
                      currentPage === 1
                        ? 'cursor-not-allowed border-line text-zinc-700'
                        : 'border-line text-zinc-400 hover:bg-zinc-900 hover:text-white'
                    }`}
                  >
                    &lt;
                  </button>

                  {/* PAGE NUMBERS */}
                  {getPageNumbers().map(
                    (page, index) => {
                      if (
                        page === '...'
                      ) {
                        return (
                          <span
                            key={`ellipsis-${index}`}
                            className="px-2 text-xs text-zinc-600"
                          >
                            ...
                          </span>
                        );
                      }

                      return (
                        <button
                          key={page}
                          type="button"
                          onClick={() =>
                            goToPage(page)
                          }
                          className={`min-w-9 rounded-xl px-3 py-2 text-xs font-semibold transition ${
                            currentPage ===
                            page
                              ? 'bg-emerald-400 text-emerald-950'
                              : 'border border-line text-zinc-400 hover:bg-zinc-900 hover:text-white'
                          }`}
                        >
                          {page}
                        </button>
                      );
                    },
                  )}

                  {/* NEXT */}
                  <button
                    type="button"
                    onClick={() =>
                      goToPage(
                        currentPage + 1,
                      )
                    }
                    disabled={
                      currentPage ===
                      totalPages
                    }
                    className={`cursor-pointer rounded-xl border px-3 py-2 text-xs font-semibold transition ${
                      currentPage ===
                      totalPages
                        ? 'cursor-not-allowed border-line text-zinc-700'
                        : 'border-line text-zinc-400 hover:bg-zinc-900 hover:text-white'
                    }`}
                  >
                    &gt;
                  </button>
                </div>
              </Reveal>
            )}

            {/* PAGINATION INFO */}
            <p className="mt-4 text-center text-[11px] text-zinc-600">
              Menampilkan{' '}
              {(currentPage - 1) *
                REPORTS_PER_PAGE +
                1}{' '}
              –{' '}
              {Math.min(
                currentPage *
                  REPORTS_PER_PAGE,
                reports.length,
              )}{' '}
              dari {reports.length}{' '}
              laporan
            </p>
          </>
        )}
    </div>
  );
}

/* =========================================================
   FORMAT TANGGAL
========================================================= */

function formatDate(
  value: string,
): string {
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