/** Label dan warna status laporan (satu tempat; dipakai histori publik dan panel moderasi). */

import type { ReportApiStatus } from '@/lib/api-types';

export const STATUS_LABEL: Record<ReportApiStatus, string> = {
  menunggu_verifikasi: 'Menunggu verifikasi',
  terverifikasi: 'Terverifikasi',
  ditandai_duplikat: 'Ditandai duplikat',
  ditandai_hoaks: 'Ditandai hoaks',
};

export const STATUS_STYLE: Record<ReportApiStatus, string> = {
  menunggu_verifikasi: 'border-amber-400/30 bg-amber-400/10 text-amber-300',
  terverifikasi: 'border-emerald-400/30 bg-emerald-400/10 text-emerald-300',
  ditandai_duplikat: 'border-sky-400/30 bg-sky-400/10 text-sky-300',
  ditandai_hoaks: 'border-red-400/30 bg-red-400/10 text-red-300',
};

/** Penjelasan singkat status, untuk pengguna awam. */
export const STATUS_HELP: Record<ReportApiStatus, string> = {
  menunggu_verifikasi: 'Sudah masuk, belum dikuatkan laporan lain atau ditinjau.',
  terverifikasi: 'Dikuatkan oleh laporan independen lain atau disetujui moderator.',
  ditandai_duplikat: 'Sangat mirip dengan laporan lain.',
  ditandai_hoaks: 'Teks tampak tidak wajar atau ditolak moderator.',
};

/** Alasan penandaan otomatis (kode dari backend) -> teks manusiawi. */
export const FLAG_REASON_LABEL: Record<string, string> = {
  tanpa_huruf: 'Teks tidak memuat huruf',
  karakter_berulang: 'Teks berisi karakter yang berulang',
  kata_berulang: 'Satu kata diulang-ulang',
  mirip_laporan_lain: 'Sangat mirip dengan laporan lain',
  ditolak_moderator: 'Ditolak oleh moderator',
};

export function flagReasonLabel(reason: string | null): string | null {
  if (!reason) return null;

  return FLAG_REASON_LABEL[reason] ?? 'Ditandai sistem';
}
