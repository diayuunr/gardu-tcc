/**
 * Logika murni formulir Lapor: pilihan jenis kejadian, validasi sesuai aturan backend, dan penyusunan body POST /reports
 * (jalur berjenjang). Aturan mengikuti backend/docs/API.md (POST /reports).
 */

import type { ApiFieldError, IncidentCategory, ReportCreateBody } from '@/lib/api-types';
import { minutesFromNow, wibInputToIso, wibInputValue } from '@/lib/format';

export const DESCRIPTION_MIN = 10;
export const DESCRIPTION_MAX = 2000;
export const JALAN_MAX = 200;
/** Backend menolak waktu kejadian > 5 menit di masa depan. */
export const FUTURE_TOLERANCE_MINUTES = 5;

/** Pilihan dropdown -> nilai `incident_type_hint` (enum backend). Kosong = tidak dikirim. */
export const INCIDENT_TYPE_OPTIONS: ReadonlyArray<{ value: '' | IncidentCategory; label: string }> = [
  { value: '', label: 'Tidak yakin / lewati' },
  { value: 'klitih', label: 'Klitih' },
  { value: 'penyerangan', label: 'Penyerangan / pembacokan' },
  { value: 'bentrok antar kelompok', label: 'Bentrok antar kelompok' },
  { value: 'begal/penodongan', label: 'Begal / penodongan / perampasan' },
  { value: 'kejadian mencurigakan', label: 'Kejadian mencurigakan' },
  { value: 'pengrusakan', label: 'Pengrusakan' },
  { value: 'lainnya', label: 'Lainnya' },
];

export type TimeMode = 'now' | 'custom';

export interface ReportFormValues {
  description: string;
  kabkota: string;
  kecamatan: string;
  kelurahan: string;
  jalan: string;
  hint: '' | IncidentCategory;
  timeMode: TimeMode;
  /** Waktu dinding WIB (YYYY-MM-DDTHH:mm), dipakai bila timeMode = 'custom'. */
  occurredAt: string;
}

export type ReportField = 'description' | 'kabkota' | 'kecamatan' | 'jalan' | 'occurredAt';
export type ReportErrors = Partial<Record<ReportField, string>>;

// Pola sama dengan backend (app/schemas/report.py): jalan berisi email/nomor telepon ditolak.
const EMAIL_PATTERN = /\S+@\S+\.\S+/;
const PHONE_PATTERN = /\d[\d\s().-]{7,}\d/;

export function validateReport(values: ReportFormValues, now: Date = new Date()): ReportErrors {
  const errors: ReportErrors = {};
  const description = values.description.trim();

  if (description.length < DESCRIPTION_MIN) {
    errors.description = `Deskripsi minimal ${DESCRIPTION_MIN} karakter. Ceritakan apa yang terjadi dan di mana.`;
  } else if (description.length > DESCRIPTION_MAX) {
    errors.description = `Deskripsi maksimal ${DESCRIPTION_MAX} karakter.`;
  }

  if (!values.kabkota) errors.kabkota = 'Pilih kabupaten/kota.';
  if (!values.kecamatan) errors.kecamatan = 'Pilih kecamatan.';

  const jalan = values.jalan.trim();

  if (jalan.length > JALAN_MAX) {
    errors.jalan = `Nama jalan atau patokan maksimal ${JALAN_MAX} karakter.`;
  } else if (EMAIL_PATTERN.test(jalan) || PHONE_PATTERN.test(jalan)) {
    errors.jalan = 'Nama jalan atau patokan tidak boleh berisi email atau nomor telepon.';
  }

  if (values.timeMode === 'custom') {
    const diff = minutesFromNow(values.occurredAt, now);

    if (diff === null) errors.occurredAt = 'Isi tanggal dan jam kejadian.';
    else if (diff > FUTURE_TOLERANCE_MINUTES) errors.occurredAt = 'Waktu kejadian tidak boleh di masa depan.';
  }

  return errors;
}

export function hasReportErrors(errors: ReportErrors): boolean {
  return Object.values(errors).some(Boolean);
}

/** Urutan bidang untuk memfokuskan galat pertama. */
export const FIELD_ORDER: readonly ReportField[] = ['description', 'kabkota', 'kecamatan', 'jalan', 'occurredAt'];

/** Body POST /reports (jalur berjenjang; `location_text` TIDAK dikirim bila kode ada). Asumsi: nilai sudah lolos validasi. */
export function buildReportBody(values: ReportFormValues, now: Date = new Date()): ReportCreateBody {
  const occurred = values.timeMode === 'now' ? wibInputValue(now) : values.occurredAt;
  const jalan = values.jalan.trim();

  return {
    description: values.description.trim(),
    occurred_at: wibInputToIso(occurred) as string,
    kabkota_kode: values.kabkota,
    kecamatan_kode: values.kecamatan,
    ...(values.kelurahan ? { kelurahan_kode: values.kelurahan } : {}),
    ...(jalan ? { jalan } : {}),
    ...(values.hint ? { incident_type_hint: values.hint } : {}),
  };
}

const SERVER_FIELD: Record<string, ReportField> = {
  description: 'description',
  kabkota_kode: 'kabkota',
  kecamatan_kode: 'kecamatan',
  kelurahan_kode: 'kecamatan',
  jalan: 'jalan',
  occurred_at: 'occurredAt',
  location_text: 'kecamatan',
};

/** Galat per-field dari 422 backend -> bidang formulir (yang tak dikenal diabaikan; ringkasan `detail` tetap ditampilkan). */
export function mapServerFieldErrors(fieldErrors: readonly ApiFieldError[]): ReportErrors {
  const mapped: ReportErrors = {};

  for (const { field, message } of fieldErrors) {
    const target = SERVER_FIELD[field];

    if (target && !mapped[target]) mapped[target] = message;
  }

  return mapped;
}
