'use client';

import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';

import Reveal from '@/components/Reveal';
import { PLACES } from '@/lib/gazetteer';

const INCIDENT_TYPES = [
  'Pencurian dengan kekerasan',
  'Pembacokan',
  'Penodongan',
  'Kejar-kejaran',
  'Pencurian kendaraan',
  'Penyerangan kelompok',
  'Lainnya',
];

type Phase = 'form' | 'sending' | 'done';

export default function LaporPage() {
  const [description, setDescription] = useState('');

  const [locationText, setLocationText] = useState(
    PLACES[0]?.name ?? ''
  );

  const [incidentType, setIncidentType] = useState(
    INCIDENT_TYPES[0]
  );

  const [occurredAt, setOccurredAt] = useState(() => {
    const d = new Date();

    d.setMinutes(
      d.getMinutes() - d.getTimezoneOffset()
    );

    return d.toISOString().slice(0, 16);
  });

  const [error, setError] = useState('');

  const [phase, setPhase] =
    useState<Phase>('form');

  const [successMessage, setSuccessMessage] =
    useState('');

  async function handleSubmit(
    e: React.FormEvent
  ) {
    e.preventDefault();

    setError('');
    setSuccessMessage('');

    /*
     * VALIDASI
     */

    if (description.trim().length < 20) {
      setError(
        'Deskripsi minimal 20 karakter agar laporan dapat diverifikasi.'
      );
      return;
    }

    if (!locationText.trim()) {
      setError(
        'Lokasi kejadian wajib diisi.'
      );
      return;
    }

    if (!occurredAt) {
      setError(
        'Waktu kejadian wajib diisi.'
      );
      return;
    }

    setPhase('sending');

    try {
      const backendUrl =
        process.env.NEXT_PUBLIC_BACKEND_URL ||
        'http://localhost:8000';

      /*
       * =====================================================
       * STEP 1
       * Kirim laporan ke Backend
       *
       * POST /reports
       *
       * Backend menerima:
       * {
       *   description,
       *   location,
       *   reported_at
       * }
       * =====================================================
       */

      const reportResponse = await fetch(
        `${backendUrl}/reports`,
        {
          method: 'POST',

          headers: {
            'Content-Type': 'application/json',
            Accept: 'application/json',
          },

          body: JSON.stringify({
            description:
              description.trim(),

            location:
              locationText.trim(),

            /*
             * Jangan menggunakan toISOString()
             * agar waktu lokal yang dipilih user
             * tidak bergeser ke UTC.
             *
             * Contoh:
             * 2026-09-20T00:00
             *
             * dikirim sebagai:
             * 2026-09-20T00:00:00
             */

            reported_at:
              `${occurredAt}:00`,
          }),
        }
      );

      /*
       * Cek apakah pembuatan laporan berhasil
       */

      if (!reportResponse.ok) {
        let detail =
          'Gagal mengirim laporan.';

        try {
          const errorData =
            await reportResponse.json();

          if (errorData?.detail) {
            detail =
              errorData.detail;
          }
        } catch {
          // Abaikan jika response bukan JSON
        }

        throw new Error(detail);
      }

      /*
       * Response dari:
       * POST /reports
       *
       * {
       *   "id": "...",
       *   "status": "menunggu_verifikasi"
       * }
       */

      const reportData =
        await reportResponse.json();

      console.log(
        '=== REPORT CREATED ==='
      );

      console.log(reportData);

      const reportId =
        reportData.id;

      /*
       * Pastikan ID laporan tersedia
       */

      if (!reportId) {
        throw new Error(
          'Laporan berhasil dikirim tetapi ID laporan tidak diterima dari server.'
        );
      }

      /*
       * =====================================================
       * STEP 2
       * Kirim laporan ke Verification Agent
       *
       * POST /agents/verify
       *
       * Backend menerima:
       * {
       *   report_id,
       *   text
       * }
       * =====================================================
       *
       * Kita gabungkan jenis kejadian + deskripsi
       * supaya Verification Agent mendapatkan konteks
       * jenis kejadian yang dipilih user.
       */

      const verificationText =
        `Jenis kejadian: ${incidentType}. ` +
        `Deskripsi: ${description.trim()}`;

      const verifyResponse =
        await fetch(
          `${backendUrl}/agents/verify`,
          {
            method: 'POST',

            headers: {
              'Content-Type':
                'application/json',

              Accept:
                'application/json',
            },

            body: JSON.stringify({
              report_id:
                reportId,

              text:
                verificationText,
            }),
          }
        );

      /*
       * Verification bisa gagal sementara
       * (misalnya Gemini/API sedang bermasalah).
       *
       * Laporan sebenarnya sudah tersimpan,
       * sehingga jangan menghapus laporan.
       */

      if (!verifyResponse.ok) {
        const verifyDetail =
          'Laporan berhasil dikirim dan menunggu verifikasi.';

        try {
          const errorData =
            await verifyResponse.json();

          if (errorData?.detail) {
            console.error(
              'Verification error:',
              errorData.detail
            );
          }
        } catch {
          // Abaikan jika response bukan JSON
        }

        console.warn(
          'Laporan tersimpan, tetapi verifikasi belum berhasil.'
        );

        setSuccessMessage(
          verifyDetail
        );

        setPhase('done');

        return;
      }

      /*
       * Response Verification Agent
       */

      const verificationData =
        await verifyResponse.json();

      console.log(
        '=== VERIFICATION RESPONSE ==='
      );

      console.log(
        verificationData
      );

      /*
       * =====================================================
       * SELESAI
       * =====================================================
       */

      setSuccessMessage(
        'Laporan berhasil dikirim dan telah masuk proses verifikasi AI.'
      );

      setPhase('done');

    } catch (err) {
      console.error(
        '=== REPORT ERROR ===',
        err
      );

      setError(
        err instanceof Error
          ? err.message
          : 'Terjadi kesalahan saat mengirim laporan.'
      );

      setPhase('form');
    }
  }

  function reset() {
    setDescription('');
    setError('');
    setSuccessMessage('');

    setIncidentType(
      INCIDENT_TYPES[0]
    );

    setPhase('form');
  }

  return (
    <div className="container-x min-h-screen pb-24 pt-32">

      <div className="mx-auto max-w-3xl">

        {/* HEADER */}
        <Reveal>

          <p className="text-xs font-semibold uppercase tracking-[0.3em] text-emerald-400">
            Lapor Kejadian
          </p>

          <h1 className="mt-3 font-display text-4xl font-bold text-white">
            Ceritakan apa yang kamu lihat.
          </h1>

          <p className="mt-3 text-zinc-500">
            Laporan bersifat{' '}
            <span className="text-emerald-300">
              anonim
            </span>
            . Tidak ada nama, nomor telepon,
            atau akun yang dikirim melalui
            formulir ini.
          </p>

        </Reveal>

        {/* FORM CARD */}
        <Reveal delay={0.15}>

          <div className="glass-card mt-10 p-6 sm:p-8">

            <AnimatePresence mode="wait">

              {/* =================================================
                  DONE
                  ================================================= */}

              {phase === 'done' ? (

                <motion.div
                  key="done"
                  initial={{
                    opacity: 0,
                    scale: 0.9,
                  }}
                  animate={{
                    opacity: 1,
                    scale: 1,
                  }}
                  className="py-10 text-center"
                >

                  <motion.div
                    initial={{
                      scale: 0,
                    }}
                    animate={{
                      scale: 1,
                    }}
                    transition={{
                      type: 'spring',
                      stiffness: 260,
                      damping: 18,
                      delay: 0.1,
                    }}
                    className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-emerald-400/10 ring-1 ring-emerald-400/30"
                  >

                    <svg
                      width="30"
                      height="30"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="#34d399"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    >
                      <path d="M5 13l4 4L19 7" />
                    </svg>

                  </motion.div>

                  <h2 className="mt-5 font-display text-2xl font-bold text-white">
                    Laporan diterima
                  </h2>

                  <p className="mx-auto mt-2 max-w-md text-sm text-zinc-500">
                    {successMessage ||
                      'Laporanmu telah diterima dan masuk proses verifikasi AI.'}
                  </p>

                  <button
                    onClick={reset}
                    className="btn-ghost mt-6 cursor-pointer"
                  >
                    Kirim laporan lain
                  </button>

                </motion.div>

              ) : (

                /* =================================================
                   FORM
                   ================================================= */

                <motion.form
                  key="form"
                  initial={{
                    opacity: 0,
                  }}
                  animate={{
                    opacity: 1,
                  }}
                  exit={{
                    opacity: 0,
                  }}
                  onSubmit={handleSubmit}
                  className="space-y-6"
                >

                  {/* JENIS KEJADIAN */}
                  <div>

                    <label className="mb-2 block text-sm font-medium text-zinc-300">
                      Jenis kejadian
                    </label>

                    <select
                      value={incidentType}
                      onChange={(e) =>
                        setIncidentType(
                          e.target.value
                        )
                      }
                      className="input"
                      disabled={
                        phase === 'sending'
                      }
                    >

                      {INCIDENT_TYPES.map(
                        (type) => (
                          <option
                            key={type}
                            value={type}
                          >
                            {type}
                          </option>
                        )
                      )}

                    </select>

                  </div>

                  {/* DESKRIPSI */}
                  <div>

                    <label className="mb-2 block text-sm font-medium text-zinc-300">
                      Deskripsi kejadian
                    </label>

                    <textarea
                      value={description}
                      onChange={(e) =>
                        setDescription(
                          e.target.value
                        )
                      }
                      rows={4}
                      placeholder="Contoh: Ada kelompok remaja menodong pengendara motor di dekat Tugu, sekitar jam setengah dua malam tadi..."
                      className="input resize-none"
                      disabled={
                        phase === 'sending'
                      }
                    />

                    <div className="mt-1.5 flex justify-between text-xs">

                      <span
                        className={
                          description.trim()
                            .length < 20
                            ? 'text-zinc-600'
                            : 'text-emerald-400'
                        }
                      >
                        Minimal 20 karakter
                      </span>

                      <span className="text-zinc-600">
                        {description.length}
                      </span>

                    </div>

                  </div>

                  {/* LOKASI + WAKTU */}
                  <div className="grid gap-6 sm:grid-cols-2">

                    {/* LOKASI */}
                    <div>

                      <label className="mb-2 block text-sm font-medium text-zinc-300">
                        Lokasi kejadian
                      </label>

                      <select
                        value={locationText}
                        onChange={(e) =>
                          setLocationText(
                            e.target.value
                          )
                        }
                        className="input"
                        disabled={
                          phase === 'sending'
                        }
                      >

                        {PLACES.map(
                          (place) => (
                            <option
                              key={place.name}
                              value={place.name}
                            >
                              {place.name}
                            </option>
                          )
                        )}

                      </select>

                    </div>

                    {/* WAKTU */}
                    <div>

                      <label className="mb-2 block text-sm font-medium text-zinc-300">
                        Perkiraan waktu kejadian
                      </label>

                      <input
                        type="datetime-local"
                        value={occurredAt}
                        onChange={(e) =>
                          setOccurredAt(
                            e.target.value
                          )
                        }
                        className="input"
                        disabled={
                          phase === 'sending'
                        }
                      />

                    </div>

                  </div>

                  {/* ERROR */}
                  {error && (

                    <motion.p
                      initial={{
                        opacity: 0,
                        y: -6,
                      }}
                      animate={{
                        opacity: 1,
                        y: 0,
                      }}
                      className="rounded-2xl border border-red-400/30 bg-red-400/10 px-4 py-3 text-sm text-red-300"
                    >
                      {error}
                    </motion.p>

                  )}

                  {/* SUBMIT */}
                  <button
                    type="submit"
                    disabled={
                      phase === 'sending'
                    }
                    className="btn-primary w-full cursor-pointer disabled:opacity-60"
                  >

                    {phase === 'sending' ? (

                      <>
                        <motion.span
                          className="h-4 w-4 rounded-full border-2 border-emerald-950/40 border-t-emerald-950"
                          animate={{
                            rotate: 360,
                          }}
                          transition={{
                            duration: 0.8,
                            repeat: Infinity,
                            ease: 'linear',
                          }}
                        />

                        Memproses laporan...
                      </>

                    ) : (

                      'Kirim Laporan Anonim'

                    )}

                  </button>

                  {/* INFO */}
                  <p className="text-center text-xs text-zinc-600">
                    Laporan akan disimpan oleh
                    server dan diproses melalui
                    Verification Agent.
                  </p>

                </motion.form>

              )}

            </AnimatePresence>

          </div>

        </Reveal>

      </div>

    </div>
  );
}