'use client';

import { useEffect, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight, RefreshCw } from 'react-feather';

import { ApiError, errorMessage, isAbortError } from '@/lib/api';
import type { ModerationList, ModerationReport, ModerationTargetStatus } from '@/lib/api-types';
import { formatDateTimeWib, formatNumber } from '@/lib/format';
import {
  DECISIONS,
  type DecisionTone,
  QUEUE_FILTERS,
  QUEUE_PAGE_SIZE,
  type QueueFilter,
  decisionMessage,
  decisionsFor,
  previewText,
} from '@/lib/moderation';
import { decideReport, fetchQueue } from '@/lib/moderation-api';
import { STATUS_HELP, STATUS_LABEL, STATUS_STYLE, flagReasonLabel } from '@/lib/report-status';

interface Props {
  onSessionEnd: (kind: 'unauthorized' | 'forbidden') => void;
}

interface Pending {
  report: ModerationReport;
  target: ModerationTargetStatus;
}

interface Notice {
  tone: 'ok' | 'error';
  text: string;
}

type QueueResult = { key: string; data?: ModerationList; error?: string };

const TONE_BUTTON: Record<DecisionTone, string> = {
  approve: 'border-emerald-400/40 bg-emerald-400/10 text-emerald-200 hover:bg-emerald-400/20',
  reject: 'border-red-400/40 bg-red-400/10 text-red-200 hover:bg-red-400/20',
  neutral: 'border-line text-zinc-300 hover:border-zinc-500 hover:text-white',
};

function ReportRow({ report, disabled, onDecide }: { report: ModerationReport; disabled: boolean; onDecide: (target: ModerationTargetStatus) => void }) {
  const [expanded, setExpanded] = useState(false);
  const preview = previewText(report.description);
  const reason = flagReasonLabel(report.flagged_reason);

  return (
    <li className="rounded-2xl border border-line bg-ink/50 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-display text-base font-semibold tracking-wide text-white">{report.nomor}</p>
          <p className="mt-0.5 text-xs text-zinc-500">Dikirim {formatDateTimeWib(report.created_at)}</p>
        </div>
        <span
          className={`shrink-0 rounded-full border px-2.5 py-1 text-[11px] font-semibold ${STATUS_STYLE[report.status]}`}
          title={STATUS_HELP[report.status]}
        >
          {STATUS_LABEL[report.status]}
        </span>
      </div>

      <p className="mt-4 whitespace-pre-wrap break-words text-sm leading-relaxed text-zinc-200">
        {expanded ? report.description : preview.text}
      </p>
      {preview.truncated && (
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          className="mt-1 text-xs font-semibold text-emerald-300 underline-offset-2 hover:underline"
          aria-expanded={expanded}
        >
          {expanded ? 'Ringkas' : 'Tampilkan selengkapnya'}
        </button>
      )}

      <dl className="mt-4 grid gap-x-6 gap-y-1.5 text-xs text-zinc-500 sm:grid-cols-2">
        <div>
          <dt className="inline">Lokasi: </dt>
          <dd className="inline text-zinc-300">{report.location_text}</dd>
        </div>
        <div>
          <dt className="inline">Kejadian: </dt>
          <dd className="inline text-zinc-300">{formatDateTimeWib(report.occurred_at)}</dd>
        </div>
        <div>
          <dt className="inline">Pilihan pelapor: </dt>
          <dd className="inline capitalize text-zinc-300">{report.incident_type_hint ?? '-'}</dd>
        </div>
        <div>
          <dt className="inline">Kategori AI: </dt>
          <dd className="inline capitalize text-zinc-300">{report.extracted_incident_type ?? '-'}</dd>
        </div>
        <div>
          <dt className="inline">Insiden: </dt>
          <dd className="inline text-zinc-300">{report.incident_id ? 'Terhubung' : 'Belum terhubung'}</dd>
        </div>
        {report.moderation_decision && (
          <div>
            <dt className="inline">Keputusan moderator: </dt>
            <dd className="inline text-zinc-300">{report.moderation_decision}</dd>
          </div>
        )}
      </dl>

      {reason && (
        <p className="mt-3 rounded-lg border border-amber-400/20 bg-amber-400/5 px-3 py-1.5 text-xs text-amber-200">
          Penandaan otomatis: {reason}
        </p>
      )}

      <div className="mt-4 flex flex-wrap gap-2 border-t border-line pt-4">
        {decisionsFor(report.status).map((target) => (
          <button
            key={target}
            type="button"
            disabled={disabled}
            onClick={() => onDecide(target)}
            className={`rounded-full border px-4 py-2 text-xs font-semibold transition disabled:cursor-not-allowed disabled:opacity-50 ${TONE_BUTTON[DECISIONS[target].tone]}`}
          >
            {DECISIONS[target].label}
          </button>
        ))}
      </div>
    </li>
  );
}

/** Antrean laporan: filter, paginasi, dan keputusan lewat dialog konfirmasi. */
export default function ModerationQueue({ onSessionEnd }: Props) {
  const [filter, setFilter] = useState<QueueFilter>('tinjau');
  const [page, setPage] = useState(0);
  const [reloadKey, setReloadKey] = useState(0);
  const [result, setResult] = useState<QueueResult | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);

  const [pending, setPending] = useState<Pending | null>(null);
  const [busy, setBusy] = useState(false);
  const [dialogError, setDialogError] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const decideAbort = useRef<AbortController | null>(null);

  const key = `${filter}|${page}|${reloadKey}`;
  const loading = result?.key !== key;

  useEffect(() => {
    const controller = new AbortController();

    fetchQueue(filter, page, controller.signal).then(
      (data) => setResult({ key, data }),
      (error: unknown) => {
        if (isAbortError(error)) return;

        if (error instanceof ApiError && (error.kind === 'unauthorized' || error.kind === 'forbidden')) {
          onSessionEnd(error.kind);
          return;
        }

        setResult({ key, error: errorMessage(error, 'Antrean laporan belum dapat dimuat.') });
      },
    );

    return () => controller.abort();
  }, [key, filter, page, onSessionEnd]);

  // Dialog asli (<dialog>): fokus terkunci di dalamnya dan Escape menutup.
  useEffect(() => {
    const dialog = dialogRef.current;

    if (!dialog) return;

    if (pending && !dialog.open) dialog.showModal();
    if (!pending && dialog.open) dialog.close();
  }, [pending]);

  useEffect(() => {
    const holder = decideAbort;

    return () => holder.current?.abort();
  }, []);

  function changeFilter(next: QueueFilter) {
    setFilter(next);
    setPage(0);
    setNotice(null);
  }

  function openDecision(report: ModerationReport, target: ModerationTargetStatus) {
    setDialogError(null);
    setPending({ report, target });
  }

  function closeDialog() {
    if (busy) return;

    setPending(null);
  }

  async function confirm() {
    if (!pending || busy) return;

    const { report, target } = pending;
    const controller = new AbortController();

    decideAbort.current = controller;
    setBusy(true);
    setDialogError(null);

    try {
      const outcome = await decideReport(report.id, target, controller.signal);

      setPending(null);
      setNotice({ tone: 'ok', text: decisionMessage(report.nomor, target, outcome) });
      setReloadKey((value) => value + 1);
    } catch (error) {
      if (isAbortError(error)) return;

      if (error instanceof ApiError && (error.kind === 'unauthorized' || error.kind === 'forbidden')) {
        setPending(null);
        onSessionEnd(error.kind);
        return;
      }

      if (error instanceof ApiError && error.kind === 'not_found') {
        setPending(null);
        setNotice({ tone: 'error', text: `Laporan ${report.nomor} tidak ditemukan; daftar dimuat ulang.` });
        setReloadKey((value) => value + 1);
        return;
      }

      setDialogError(errorMessage(error, 'Keputusan belum dapat disimpan. Coba lagi.'));
    } finally {
      setBusy(false);
    }
  }

  const items = result?.data?.items ?? [];
  const total = result?.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / QUEUE_PAGE_SIZE));
  const failed = !loading && result?.error;
  const copy = pending ? DECISIONS[pending.target] : null;

  return (
    <div>
      <div className="flex flex-wrap gap-2" role="group" aria-label="Filter antrean">
        {QUEUE_FILTERS.map((option) => (
          <button
            key={option.value}
            type="button"
            onClick={() => changeFilter(option.value)}
            aria-pressed={filter === option.value}
            className={`rounded-full border px-4 py-1.5 text-xs font-semibold transition ${
              filter === option.value
                ? 'border-emerald-400/50 bg-emerald-400/10 text-emerald-200'
                : 'border-line text-zinc-400 hover:border-zinc-500 hover:text-white'
            }`}
          >
            {option.label}
          </button>
        ))}
      </div>

      <p className="mt-4 text-xs leading-relaxed text-zinc-500">
        Isi laporan bersifat sensitif. Gunakan hanya untuk keperluan moderasi dan jangan menyalin atau membagikannya di luar
        panel ini.
      </p>

      {notice && (
        <p
          className={`mt-4 rounded-xl border px-4 py-2.5 text-sm ${
            notice.tone === 'ok'
              ? 'border-emerald-400/20 bg-emerald-400/5 text-emerald-200'
              : 'border-red-400/20 bg-red-400/5 text-red-200'
          }`}
          role={notice.tone === 'ok' ? 'status' : 'alert'}
        >
          {notice.text}
        </p>
      )}

      <section className="mt-6" aria-busy={loading} aria-label="Daftar laporan">
        {!loading && !failed && total > 0 && (
          <p className="mb-3 text-xs text-zinc-500" aria-live="polite">
            Menampilkan {page * QUEUE_PAGE_SIZE + 1}-{page * QUEUE_PAGE_SIZE + items.length} dari {formatNumber(total)} laporan
          </p>
        )}

        {loading && (
          <ul className="space-y-4" aria-hidden="true">
            {Array.from({ length: 3 }).map((_, index) => (
              <li key={index} className="h-48 animate-pulse rounded-2xl border border-line bg-ink/50 motion-reduce:animate-none" />
            ))}
          </ul>
        )}

        {failed && (
          <div className="rounded-2xl border border-red-400/20 bg-red-400/5 p-8 text-center" role="alert">
            <p className="text-sm text-red-200">{result?.error}</p>
            <button type="button" onClick={() => setReloadKey((value) => value + 1)} className="btn-ghost mt-5 !px-5 !py-2">
              <RefreshCw size={14} aria-hidden="true" />
              Coba lagi
            </button>
          </div>
        )}

        {!loading && !failed && items.length === 0 && (
          <div className="rounded-2xl border border-line bg-ink/40 p-10 text-center">
            <p className="font-display text-lg font-semibold text-white">
              {page > 0 ? 'Halaman ini kosong' : 'Tidak ada laporan pada filter ini'}
            </p>
            <p className="mt-2 text-sm text-zinc-500">
              {page > 0 ? 'Kembali ke halaman pertama.' : 'Antrean kosong atau semua sudah ditinjau.'}
            </p>
            {page > 0 && (
              <button type="button" onClick={() => setPage(0)} className="btn-ghost mt-5 !px-5 !py-2">
                Ke halaman pertama
              </button>
            )}
          </div>
        )}

        {!loading && !failed && items.length > 0 && (
          <ul className="space-y-4">
            {items.map((report) => (
              <ReportRow key={report.id} report={report} disabled={busy} onDecide={(target) => openDecision(report, target)} />
            ))}
          </ul>
        )}

        {!failed && total > QUEUE_PAGE_SIZE && (
          <nav className="mt-6 flex items-center justify-between gap-3" aria-label="Paginasi antrean">
            <button
              type="button"
              onClick={() => setPage(page - 1)}
              disabled={page === 0 || loading}
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
              onClick={() => setPage(page + 1)}
              disabled={page + 1 >= pages || loading}
              className="btn-ghost !px-4 !py-2 disabled:cursor-not-allowed disabled:opacity-40"
            >
              Berikutnya
              <ChevronRight size={16} aria-hidden="true" />
            </button>
          </nav>
        )}
      </section>

      <dialog
        ref={dialogRef}
        onClose={closeDialog}
        onCancel={(event) => {
          if (busy) event.preventDefault();
        }}
        aria-labelledby="mod-dialog-title"
        className="m-auto w-[calc(100%-2rem)] max-w-md rounded-3xl border border-line bg-panel p-6 text-zinc-100 backdrop:bg-black/70"
      >
        {pending && copy && (
          <div>
            <h2 id="mod-dialog-title" className="font-display text-lg font-bold text-white">
              {copy.title}
            </h2>
            <p className="mt-1 text-xs text-zinc-500">{pending.report.nomor}</p>
            <p className="mt-4 text-sm leading-relaxed text-zinc-400">{copy.body}</p>

            {dialogError && (
              <p className="mt-4 text-xs text-red-300" role="alert">
                {dialogError}
              </p>
            )}

            <div className="mt-6 flex flex-wrap justify-end gap-3">
              <button type="button" onClick={closeDialog} disabled={busy} className="btn-ghost !px-5 !py-2 disabled:opacity-50" autoFocus>
                Batal
              </button>
              <button
                type="button"
                onClick={() => void confirm()}
                disabled={busy}
                className={`rounded-full border px-5 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-60 ${TONE_BUTTON[copy.tone]}`}
              >
                {busy ? 'Menyimpan…' : copy.confirm}
              </button>
            </div>
          </div>
        )}
      </dialog>
    </div>
  );
}
