'use client';

import { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';

import Reveal from '@/components/Reveal';
import { supabase } from '@/lib/supabase';
import { BACKEND_URL, readErrorDetail } from '@/lib/api';

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

type Area = {
  kode: string;
  nama: string;
  tingkat: 'kabkota' | 'kecamatan' | 'kelurahan';
  parent_kode: string | null;
};

export default function LaporPage() {
  const [description, setDescription] = useState('');

  const [areas, setAreas] = useState<Area[]>([]);
  const [areasLoading, setAreasLoading] = useState(true);
  const [areasError, setAreasError] = useState('');
  const [kabkotaKode, setKabkotaKode] = useState('');
  const [kecamatanKode, setKecamatanKode] = useState('');
  const [kelurahanKode, setKelurahanKode] = useState('');
  const [jalan, setJalan] = useState('');

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

  useEffect(() => {
    let active = true;

    async function loadAreas() {
      if (!supabase) {
        if (active) {
          setAreasError('Konfigurasi Supabase belum tersedia. Periksa NEXT_PUBLIC_SUPABASE_URL dan NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY.');
          setAreasLoading(false);
        }
        return;
      }

      const { data, error: queryError } = await supabase
        .from('areas')
        .select('kode, nama, tingkat, parent_kode')
        .in('tingkat', ['kabkota', 'kecamatan', 'kelurahan'])
        .order('nama', { ascending: true });

      if (!active) return;

      if (queryError) {
        setAreasError('Daftar wilayah gagal dimuat dari Supabase. Pastikan tabel areas dapat dibaca oleh public/anon.');
        setAreasLoading(false);
        console.error('Gagal memuat areas:', queryError);
        return;
      }

      setAreas((data ?? []) as Area[]);
      setAreasLoading(false);
    }

    loadAreas();
    return () => { active = false; };
  }, []);

  const kabkotaOptions = areas.filter((area) => area.tingkat === 'kabkota');
  const kecamatanOptions = areas.filter(
    (area) => area.tingkat === 'kecamatan' && area.parent_kode === kabkotaKode
  );
  const kelurahanOptions = areas.filter(
    (area) => area.tingkat === 'kelurahan' && area.parent_kode === kecamatanKode
  );

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

    if (!kabkotaKode || !kecamatanKode) {
      setError('Kabupaten/kota dan kecamatan wajib dipilih.');
      return;
    }

    if (jalan.trim().length > 200) {
      setError('Nama jalan atau patokan maksimal 200 karakter.');
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
      // Backend baru menerima lokasi sebagai teks, jadi nama wilayah yang
      // dipilih digabung dari yang paling spesifik ke yang paling umum.
      const nameOf = (kode: string) =>
        areas.find((area) => area.kode === kode)?.nama;

      const locationText = [
        jalan.trim(),
        kelurahanKode ? nameOf(kelurahanKode) : undefined,
        nameOf(kecamatanKode),
        nameOf(kabkotaKode),
      ]
        .filter(Boolean)
        .join(', ')
        .slice(0, 200);

      // Verifikasi AI berjalan otomatis di background backend setelah
      // laporan tersimpan, jadi cukup satu panggilan ke POST /reports.
      // Backend belum punya field jenis kejadian, jadi dilampirkan di
      // awal deskripsi agar tetap terbaca oleh verifikator.
      const response = await fetch(`${BACKEND_URL}/reports`, {
        method: 'POST',

        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
        },

        body: JSON.stringify({
          description: `Jenis kejadian: ${incidentType}. ${description.trim()}`,
          location_text: locationText,

          // Instan absolut (UTC) dari waktu lokal yang dipilih. Tanpa
          // zona waktu, backend menganggapnya UTC dan menolak waktu
          // "sekarang" sebagai masa depan.
          occurred_at: new Date(occurredAt).toISOString(),
        }),
      });

      if (!response.ok) {
        throw new Error(
          await readErrorDetail(response, 'Gagal mengirim laporan.'),
        );
      }

      setSuccessMessage(
        'Laporan berhasil dikirim dan akan diverifikasi secara otomatis.',
      );

      setPhase('done');
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : 'Terjadi kesalahan saat mengirim laporan.',
      );

      setPhase('form');
    }
  }

  function reset() {
    setDescription('');
    setKabkotaKode('');
    setKecamatanKode('');
    setKelurahanKode('');
    setJalan('');
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

                  {/* LOKASI BERJENJANG DARI SUPABASE */}
                  <div className="space-y-5">
                    <div>
                      <label className="mb-2 block text-sm font-medium text-zinc-300">
                        Kabupaten/kota <span className="text-emerald-300">*</span>
                      </label>
                      <select
                        value={kabkotaKode}
                        onChange={(e) => {
                          setKabkotaKode(e.target.value);
                          setKecamatanKode('');
                          setKelurahanKode('');
                        }}
                        className="input"
                        disabled={phase === 'sending' || areasLoading || !!areasError}
                        required
                      >
                        <option value="">Pilih kabupaten/kota</option>
                        {kabkotaOptions.map((area) => (
                          <option key={area.kode} value={area.kode}>{area.nama}</option>
                        ))}
                      </select>
                    </div>

                    <div className="grid gap-5 sm:grid-cols-2">
                      <div>
                        <label className="mb-2 block text-sm font-medium text-zinc-300">
                          Kecamatan <span className="text-emerald-300">*</span>
                        </label>
                        <select
                          value={kecamatanKode}
                          onChange={(e) => {
                            setKecamatanKode(e.target.value);
                            setKelurahanKode('');
                          }}
                          className="input"
                          disabled={phase === 'sending' || !kabkotaKode || areasLoading}
                          required
                        >
                          <option value="">Pilih kecamatan</option>
                          {kecamatanOptions.map((area) => (
                            <option key={area.kode} value={area.kode}>{area.nama}</option>
                          ))}
                        </select>
                      </div>

                      <div>
                        <label className="mb-2 block text-sm font-medium text-zinc-300">
                          Kelurahan/desa <span className="text-zinc-500">(opsional)</span>
                        </label>
                        <select
                          value={kelurahanKode}
                          onChange={(e) => setKelurahanKode(e.target.value)}
                          className="input"
                          disabled={phase === 'sending' || !kecamatanKode || areasLoading}
                        >
                          <option value="">Pilih kelurahan/desa</option>
                          {kelurahanOptions.map((area) => (
                            <option key={area.kode} value={area.kode}>{area.nama}</option>
                          ))}
                        </select>
                      </div>
                    </div>

                    <div>
                      <label className="mb-2 block text-sm font-medium text-zinc-300">
                        Nama jalan atau patokan <span className="text-zinc-500">(opsional)</span>
                      </label>
                      <input
                        type="text"
                        value={jalan}
                        onChange={(e) => setJalan(e.target.value)}
                        maxLength={200}
                        placeholder="Contoh: Jalan Kaliurang, dekat lampu merah"
                        className="input"
                        disabled={phase === 'sending'}
                      />
                      <p className="mt-1 text-xs text-zinc-600">Maksimal 200 karakter. Jangan masukkan informasi identitas pribadi.</p>
                    </div>

                    {areasLoading && (
                      <p className="text-xs text-zinc-500">Memuat daftar wilayah dari Supabase...</p>
                    )}
                    {areasError && (
                      <p className="rounded-xl border border-amber-400/30 bg-amber-400/10 px-3 py-2 text-sm text-amber-200">{areasError}</p>
                    )}
                    {!areasLoading && !areasError && kabkotaOptions.length === 0 && (
                      <p className="text-xs text-amber-300">Data wilayah belum tersedia di tabel areas.</p>
                    )}
                  </div>

                  {/* WAKTU */}
                  <div>
                    <label className="mb-2 block text-sm font-medium text-zinc-300">
                      Perkiraan waktu kejadian
                    </label>
                    <input
                      type="datetime-local"
                      value={occurredAt}
                      onChange={(e) => setOccurredAt(e.target.value)}
                      className="input"
                      disabled={phase === 'sending'}
                      required
                    />
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
                    Laporan disimpan oleh server dan
                    diverifikasi otomatis di latar
                    belakang.
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