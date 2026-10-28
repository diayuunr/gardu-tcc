'use client';

import Link from 'next/link';
import { AnimatePresence, motion } from 'framer-motion';
import { useEffect, useRef, useState } from 'react';
import { Lock } from 'react-feather';

import { useAreas } from '@/hooks/useAreas';
import { invalidateApiCache } from '@/hooks/useApiQuery';
import { ApiError, apiPost, errorMessage } from '@/lib/api';
import type { ReportCreated } from '@/lib/api-types';
import { wibInputValue } from '@/lib/format';
import {
  DESCRIPTION_MAX,
  DESCRIPTION_MIN,
  FIELD_ORDER,
  INCIDENT_TYPE_OPTIONS,
  JALAN_MAX,
  ReportErrors,
  ReportField,
  ReportFormValues,
  TimeMode,
  buildReportBody,
  hasReportErrors,
  mapServerFieldErrors,
  validateReport,
} from '@/lib/report';

type Phase = 'form' | 'sending' | 'done';

const INITIAL: ReportFormValues = {
  description: '',
  kabkota: '',
  kecamatan: '',
  kelurahan: '',
  jalan: '',
  hint: '',
  timeMode: 'now',
  occurredAt: '',
};

const FIELD_ID: Record<ReportField, string> = {
  description: 'lapor-deskripsi',
  kabkota: 'lapor-kabkota',
  kecamatan: 'lapor-kecamatan',
  jalan: 'lapor-jalan',
  occurredAt: 'lapor-waktu',
};

function FieldError({ id, message }: { id: string; message?: string }) {
  if (!message) return null;

  return (
    <p id={`${id}-error`} role="alert" className="mt-1.5 text-xs text-red-300">
      {message}
    </p>
  );
}

function AreaSelect({
  id,
  label,
  optional = false,
  value,
  onChange,
  placeholder,
  areas,
  loading,
  error,
  onRetry,
  disabled,
  fieldError,
}: {
  id: string;
  label: string;
  optional?: boolean;
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  areas: { kode: string; nama: string }[];
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  disabled: boolean;
  fieldError?: string;
}) {
  return (
    <div>
      <label htmlFor={id} className="mb-2 block text-sm font-medium text-zinc-300">
        {label}{' '}
        {optional ? (
          <span className="text-zinc-500">(opsional)</span>
        ) : (
          <span className="text-emerald-300" aria-hidden="true">
            *
          </span>
        )}
      </label>

      <select
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="input"
        disabled={disabled || loading || Boolean(error)}
        aria-required={!optional}
        aria-invalid={fieldError ? true : undefined}
        aria-describedby={fieldError ? `${id}-error` : undefined}
        aria-busy={loading}
      >
        <option value="">{loading ? 'Memuat...' : placeholder}</option>
        {areas.map((area) => (
          <option key={area.kode} value={area.kode}>
            {area.nama}
          </option>
        ))}
      </select>

      {error && (
        <p role="alert" className="mt-1.5 text-xs text-amber-300">
          {error}{' '}
          <button type="button" onClick={onRetry} className="font-semibold underline underline-offset-2">
            Muat ulang
          </button>
        </p>
      )}

      <FieldError id={id} message={fieldError} />
    </div>
  );
}

/** Formulir Lapor Kejadian anonim: wilayah berjenjang dari GET /areas, kirim ke POST /reports. */
export default function ReportForm() {
  const [values, setValues] = useState<ReportFormValues>(INITIAL);
  const [errors, setErrors] = useState<ReportErrors>({});
  const [summary, setSummary] = useState('');
  const [phase, setPhase] = useState<Phase>('form');
  const [maxOccurred, setMaxOccurred] = useState('');

  const submittingRef = useRef(false);
  const doneHeadingRef = useRef<HTMLHeadingElement>(null);

  const kabkota = useAreas('kabkota', null);
  const kecamatan = useAreas('kecamatan', values.kabkota || null);
  const kelurahan = useAreas('kelurahan', values.kecamatan || null);

  const sending = phase === 'sending';
  const descriptionLength = values.description.trim().length;

  useEffect(() => {
    if (phase === 'done') doneHeadingRef.current?.focus();
  }, [phase]);

  function update<K extends keyof ReportFormValues>(key: K, value: ReportFormValues[K], clear?: ReportField) {
    setValues((current) => ({ ...current, [key]: value }));

    if (clear) setErrors((current) => ({ ...current, [clear]: undefined }));
  }

  function chooseTimeMode(mode: TimeMode) {
    update('timeMode', mode, 'occurredAt');

    if (mode === 'custom' && !values.occurredAt) {
      const now = wibInputValue();

      setMaxOccurred(now);
      update('occurredAt', now);
    }
  }

  function focusFirst(found: ReportErrors) {
    const first = FIELD_ORDER.find((field) => found[field]);

    if (first) document.getElementById(FIELD_ID[first])?.focus();
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();

    if (submittingRef.current) return; // cegah kirim ganda (klik dua kali / Enter berulang)

    const found = validateReport(values);

    setErrors(found);
    setSummary('');

    if (hasReportErrors(found)) {
      setSummary('Periksa isian yang ditandai merah, lalu kirim lagi.');
      focusFirst(found);
      return;
    }

    submittingRef.current = true;
    setPhase('sending');

    try {
      await apiPost<ReportCreated>('/reports', buildReportBody(values), { timeoutMs: 15_000 });
      // Histori dan statistik publik harus langsung menampilkan laporan baru (bukan hasil tersimpan 30 dtk lalu).
      invalidateApiCache('/reports');

      setPhase('done');
    } catch (error) {
      const serverErrors = error instanceof ApiError ? mapServerFieldErrors(error.fieldErrors) : {};

      setErrors(serverErrors);
      setSummary(errorMessage(error, 'Laporan belum dapat dikirim. Silakan coba lagi.'));
      setPhase('form');
      focusFirst(serverErrors);
    } finally {
      submittingRef.current = false;
    }
  }

  function reset() {
    setValues(INITIAL);
    setErrors({});
    setSummary('');
    setPhase('form');
  }

  return (
    <div className="glass-card mt-10 p-6 sm:p-8">
      <AnimatePresence mode="wait">
        {phase === 'done' ? (
          <motion.div
            key="done"
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            className="py-8 text-center"
            role="status"
          >
            <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-emerald-400/10 ring-1 ring-emerald-400/30">
              <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="#34d399" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M5 13l4 4L19 7" />
              </svg>
            </div>

            <h2 ref={doneHeadingRef} tabIndex={-1} className="mt-5 font-display text-2xl font-bold text-white outline-none">
              Laporan diterima
            </h2>

            <p className="mx-auto mt-3 max-w-md text-sm leading-relaxed text-zinc-400">
              Terima kasih. Laporan Anda sudah masuk dan akan diproses otomatis di latar belakang, lalu dapat ditinjau
              moderator. Hasil pemeriksaan tidak dijamin dan laporan yang baru dikirim mungkin belum langsung tampil di
              histori.
            </p>

            <div className="mt-6 flex flex-wrap justify-center gap-3">
              <button type="button" onClick={reset} className="btn-primary cursor-pointer">
                Kirim laporan lain
              </button>
              <Link href="/laporan" className="btn-ghost">
                Lihat histori laporan
              </Link>
            </div>
          </motion.div>
        ) : (
          <motion.form
            key="form"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onSubmit={handleSubmit}
            className="space-y-6"
            noValidate
            aria-busy={sending}
          >
            <p className="flex gap-3 rounded-2xl border border-emerald-400/20 bg-emerald-400/5 px-4 py-3 text-xs leading-relaxed text-zinc-400">
              <Lock size={14} className="mt-0.5 shrink-0 text-emerald-300" aria-hidden="true" />
              <span>
                Jangan cantumkan <strong className="text-zinc-300">nama, nomor telepon, atau email</strong>. Bila
                tertulis, akan disamarkan otomatis sebelum disimpan.
              </span>
            </p>

            <div>
              <label htmlFor="lapor-jenis" className="mb-2 block text-sm font-medium text-zinc-300">
                Jenis kejadian <span className="text-zinc-500">(opsional)</span>
              </label>
              <select
                id="lapor-jenis"
                value={values.hint}
                onChange={(event) => update('hint', event.target.value as ReportFormValues['hint'])}
                className="input"
                disabled={sending}
              >
                {INCIDENT_TYPE_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label htmlFor="lapor-deskripsi" className="mb-2 block text-sm font-medium text-zinc-300">
                Deskripsi kejadian{' '}
                <span className="text-emerald-300" aria-hidden="true">
                  *
                </span>
              </label>
              <textarea
                id="lapor-deskripsi"
                value={values.description}
                onChange={(event) => update('description', event.target.value, 'description')}
                rows={5}
                maxLength={DESCRIPTION_MAX}
                placeholder="Ceritakan apa yang terjadi: kapan, di dekat apa, dan apa yang Anda lihat. Contoh: sekelompok pengendara motor membawa senjata tajam di dekat simpang..."
                className="input resize-y"
                disabled={sending}
                aria-required="true"
                aria-invalid={errors.description ? true : undefined}
                aria-describedby={`lapor-deskripsi-info${errors.description ? ' lapor-deskripsi-error' : ''}`}
              />
              <div id="lapor-deskripsi-info" className="mt-1.5 flex justify-between gap-3 text-xs">
                <span className={descriptionLength < DESCRIPTION_MIN ? 'text-zinc-600' : 'text-emerald-400'}>
                  Minimal {DESCRIPTION_MIN} karakter; makin rinci makin mudah diperiksa
                </span>
                <span className="shrink-0 text-zinc-600">
                  {values.description.length}/{DESCRIPTION_MAX}
                </span>
              </div>
              <FieldError id="lapor-deskripsi" message={errors.description} />
            </div>

            <fieldset className="space-y-5" disabled={sending}>
              <legend className="mb-3 text-sm font-medium text-zinc-300">Lokasi kejadian</legend>

              <AreaSelect
                id="lapor-kabkota"
                label="Kabupaten/kota"
                value={values.kabkota}
                onChange={(value) => {
                  setValues((current) => ({ ...current, kabkota: value, kecamatan: '', kelurahan: '' }));
                  setErrors((current) => ({ ...current, kabkota: undefined, kecamatan: undefined }));
                }}
                placeholder="Pilih kabupaten/kota"
                areas={kabkota.areas}
                loading={kabkota.loading}
                error={kabkota.error}
                onRetry={kabkota.retry}
                disabled={sending}
                fieldError={errors.kabkota}
              />

              <div className="grid gap-5 sm:grid-cols-2">
                <AreaSelect
                  id="lapor-kecamatan"
                  label="Kecamatan"
                  value={values.kecamatan}
                  onChange={(value) => {
                    setValues((current) => ({ ...current, kecamatan: value, kelurahan: '' }));
                    setErrors((current) => ({ ...current, kecamatan: undefined }));
                  }}
                  placeholder={values.kabkota ? 'Pilih kecamatan' : 'Pilih kabupaten/kota dulu'}
                  areas={kecamatan.areas}
                  loading={kecamatan.loading}
                  error={kecamatan.error}
                  onRetry={kecamatan.retry}
                  disabled={sending || !values.kabkota}
                  fieldError={errors.kecamatan}
                />

                <AreaSelect
                  id="lapor-kelurahan"
                  label="Kelurahan/desa"
                  optional
                  value={values.kelurahan}
                  onChange={(value) => update('kelurahan', value)}
                  placeholder={values.kecamatan ? 'Pilih kelurahan/desa' : 'Pilih kecamatan dulu'}
                  areas={kelurahan.areas}
                  loading={kelurahan.loading}
                  error={kelurahan.error}
                  onRetry={kelurahan.retry}
                  disabled={sending || !values.kecamatan}
                />
              </div>

              <div>
                <label htmlFor="lapor-jalan" className="mb-2 block text-sm font-medium text-zinc-300">
                  Nama jalan atau patokan <span className="text-zinc-500">(opsional)</span>
                </label>
                <input
                  id="lapor-jalan"
                  type="text"
                  value={values.jalan}
                  onChange={(event) => update('jalan', event.target.value, 'jalan')}
                  maxLength={JALAN_MAX}
                  placeholder="Contoh: Jalan Kaliurang, dekat lampu merah"
                  className="input"
                  autoComplete="off"
                  aria-invalid={errors.jalan ? true : undefined}
                  aria-describedby={`lapor-jalan-info${errors.jalan ? ' lapor-jalan-error' : ''}`}
                />
                <p id="lapor-jalan-info" className="mt-1.5 text-xs text-zinc-600">
                  Maksimal {JALAN_MAX} karakter. Bagian ini bersifat privat dan tidak ditampilkan ke publik.
                </p>
                <FieldError id="lapor-jalan" message={errors.jalan} />
              </div>
            </fieldset>

            <fieldset className="space-y-2" disabled={sending}>
              <legend className="mb-2 text-sm font-medium text-zinc-300">Waktu kejadian (WIB)</legend>

              <div className="inline-flex rounded-full border border-line p-1" role="group" aria-label="Pilih waktu kejadian">
                {(
                  [
                    ['now', 'Baru saja'],
                    ['custom', 'Atur waktu'],
                  ] as const
                ).map(([mode, text]) => (
                  <button
                    key={mode}
                    type="button"
                    aria-pressed={values.timeMode === mode}
                    onClick={() => chooseTimeMode(mode)}
                    className={`rounded-full px-4 py-1.5 text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400/60 ${
                      values.timeMode === mode ? 'bg-emerald-400 text-emerald-950' : 'text-zinc-400 hover:text-zinc-200'
                    }`}
                  >
                    {text}
                  </button>
                ))}
              </div>

              {values.timeMode === 'custom' && (
                <div>
                  <label htmlFor="lapor-waktu" className="sr-only">
                    Tanggal dan jam kejadian (WIB)
                  </label>
                  <input
                    id="lapor-waktu"
                    type="datetime-local"
                    value={values.occurredAt}
                    max={maxOccurred || undefined}
                    onChange={(event) => update('occurredAt', event.target.value, 'occurredAt')}
                    className="input"
                    aria-invalid={errors.occurredAt ? true : undefined}
                    aria-describedby={errors.occurredAt ? 'lapor-waktu-error' : undefined}
                  />
                </div>
              )}

              <p className="text-xs text-zinc-600">Perkiraan sudah cukup. Waktu tidak boleh di masa depan.</p>
              <FieldError id="lapor-waktu" message={errors.occurredAt} />
            </fieldset>

            <div aria-live="polite">
              {summary && (
                <motion.p
                  initial={{ opacity: 0, y: -6 }}
                  animate={{ opacity: 1, y: 0 }}
                  role="alert"
                  className="rounded-2xl border border-red-400/30 bg-red-400/10 px-4 py-3 text-sm leading-relaxed text-red-200"
                >
                  {summary}
                </motion.p>
              )}
            </div>

            <button type="submit" disabled={sending} className="btn-primary w-full cursor-pointer disabled:cursor-not-allowed disabled:opacity-60">
              {sending ? (
                <>
                  <span className="h-4 w-4 animate-spin rounded-full border-2 border-emerald-950/40 border-t-emerald-950 motion-reduce:animate-none" aria-hidden="true" />
                  Mengirim laporan...
                </>
              ) : (
                'Kirim Laporan Anonim'
              )}
            </button>

            <p className="text-center text-xs leading-relaxed text-zinc-600">
              Laporan disimpan oleh server dan diperiksa otomatis di latar belakang. Pemeriksaan tidak menjamin laporan
              akan terverifikasi.
            </p>
          </motion.form>
        )}
      </AnimatePresence>
    </div>
  );
}
