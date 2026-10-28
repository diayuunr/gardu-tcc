/** Logika murni panel moderasi: filter antrean, pilihan keputusan, dan teks pesan. Tanpa jaringan/DOM agar mudah diuji. */

import type { ModerationResult, ModerationTargetStatus, ReportApiStatus } from '@/lib/api-types';
import { STATUS_LABEL } from '@/lib/report-status';

export const QUEUE_PAGE_SIZE = 20;

/** 'tinjau' = bawaan backend (menunggu + ditandai duplikat/hoaks), tanpa parameter `status`. */
export type QueueFilter = 'tinjau' | ReportApiStatus;

export const QUEUE_FILTERS: ReadonlyArray<{ value: QueueFilter; label: string }> = [
  { value: 'tinjau', label: 'Perlu tinjauan' },
  { value: 'menunggu_verifikasi', label: STATUS_LABEL.menunggu_verifikasi },
  { value: 'ditandai_duplikat', label: STATUS_LABEL.ditandai_duplikat },
  { value: 'ditandai_hoaks', label: STATUS_LABEL.ditandai_hoaks },
  { value: 'terverifikasi', label: STATUS_LABEL.terverifikasi },
];

export function filterToStatus(filter: QueueFilter): ReportApiStatus | undefined {
  return filter === 'tinjau' ? undefined : filter;
}

export type DecisionTone = 'approve' | 'reject' | 'neutral';

export interface DecisionCopy {
  /** Teks tombol di kartu. */
  label: string;
  /** Judul dan isi dialog konfirmasi. */
  title: string;
  body: string;
  confirm: string;
  tone: DecisionTone;
  /** Kalimat hasil (dipakai setelah berhasil), tanpa nomor. */
  done: string;
}

export const DECISIONS: Record<ModerationTargetStatus, DecisionCopy> = {
  terverifikasi: {
    label: 'Setujui',
    title: 'Setujui laporan ini?',
    body: 'Laporan menjadi terverifikasi dan insidennya dihitung terverifikasi walau baru satu laporan. Skor kerawanan akan dihitung ulang di latar belakang.',
    confirm: 'Ya, setujui',
    tone: 'approve',
    done: 'disetujui',
  },
  ditandai_hoaks: {
    label: 'Tolak',
    title: 'Tolak laporan ini?',
    body: 'Laporan ditandai ditolak dan dicabut dari insidennya sehingga tidak ikut dihitung. Keputusan dapat dibatalkan dengan mengembalikannya ke antrean.',
    confirm: 'Ya, tolak',
    tone: 'reject',
    done: 'ditolak',
  },
  menunggu_verifikasi: {
    label: 'Kembalikan ke antrean',
    title: 'Kembalikan ke antrean?',
    body: 'Keputusan dan penandaan dihapus. Laporan dicabut dari insidennya lalu dikelompokkan ulang oleh sistem pada proses berikutnya.',
    confirm: 'Ya, kembalikan',
    tone: 'neutral',
    done: 'dikembalikan ke antrean',
  },
};

const ORDER: ModerationTargetStatus[] = ['terverifikasi', 'ditandai_hoaks', 'menunggu_verifikasi'];

/** Keputusan yang masuk akal untuk status sekarang: semua kecuali yang sudah berlaku. */
export function decisionsFor(status: ReportApiStatus): ModerationTargetStatus[] {
  return ORDER.filter((target) => target !== status);
}

/** Kalimat hasil keputusan yang jujur: `changed=false` berarti tidak ada yang berubah. */
export function decisionMessage(nomor: string, target: ModerationTargetStatus, result: ModerationResult): string {
  if (!result.changed) {
    return `Laporan ${nomor} sudah berada pada keputusan ini; tidak ada perubahan.`;
  }

  const refresh = result.scores_refresh_scheduled ? ' Skor kerawanan sedang dihitung ulang.' : '';

  return `Laporan ${nomor} ${DECISIONS[target].done}.${refresh}`;
}

/** Potong teks panjang di batas kata agar kartu tetap ringkas; `truncated` memberi tahu bila ada sisa. */
export function previewText(text: string, max = 280): { text: string; truncated: boolean } {
  const clean = text.trim();

  if (clean.length <= max) return { text: clean, truncated: false };

  const cut = clean.slice(0, max);
  const lastSpace = cut.lastIndexOf(' ');

  return { text: `${(lastSpace > max * 0.6 ? cut.slice(0, lastSpace) : cut).trimEnd()}…`, truncated: true };
}
