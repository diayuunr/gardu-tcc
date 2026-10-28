'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { ApiError, ApiErrorKind, apiPost, errorMessage, isAbortError } from '@/lib/api';
import type { RouteCheck, RouteCheckBody } from '@/lib/api-types';

/** Tahap tampilan saat memuat (hanya penanda kemajuan; backend tidak mengirim progres nyata). */
export const LOADING_STEPS = [
  'Mencari rute terbaik',
  'Memeriksa riwayat kejadian di sepanjang jalan',
  'Menyusun hasil',
] as const;

const STEP_DELAYS_MS = [2200, 5200];

export type RouteCheckState =
  | { status: 'idle' }
  | { status: 'loading'; step: number }
  | { status: 'success'; data: RouteCheck }
  | { status: 'error'; message: string; kind: ApiErrorKind | 'unknown' };

/** Pesan untuk galat Cek Rute; pesan backend (422/429/503) dipakai apa adanya karena sudah aman ditampilkan. */
export function routeErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.kind === 'timeout') {
      return 'Pemeriksaan rute memakan waktu terlalu lama. Silakan coba lagi sebentar lagi.';
    }

    return error.message;
  }

  return errorMessage(error, 'Terjadi kesalahan saat memeriksa rute. Silakan coba lagi.');
}

/**
 * Siklus permintaan POST /route/check: memuat -> berhasil/galat, dengan pembatalan permintaan usang
 * (memeriksa lagi membatalkan yang sebelumnya). Titik dikirim sebagai KOORDINAT hasil pilihan, bukan teks.
 */
export function useRouteCheck() {
  const [state, setState] = useState<RouteCheckState>({ status: 'idle' });
  const controllerRef = useRef<AbortController | null>(null);
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  const clearTimers = useCallback(() => {
    timersRef.current.forEach(clearTimeout);
    timersRef.current = [];
  }, []);

  useEffect(() => {
    const controller = controllerRef;
    const clear = clearTimers;

    return () => {
      controller.current?.abort();
      clear();
    };
  }, [clearTimers]);

  const check = useCallback(
    async (body: RouteCheckBody, options: { narrative: boolean }) => {
      controllerRef.current?.abort();
      clearTimers();

      const controller = new AbortController();

      controllerRef.current = controller;
      setState({ status: 'loading', step: 0 });

      timersRef.current = STEP_DELAYS_MS.map((delay, position) =>
        setTimeout(() => {
          setState((current) =>
            current.status === 'loading' ? { status: 'loading', step: position + 1 } : current,
          );
        }, delay),
      );

      try {
        const data = await apiPost<RouteCheck>('/route/check', body, {
          signal: controller.signal,
          timeoutMs: 60_000,
          query: options.narrative ? { include_narrative: true } : undefined,
        });

        if (controller.signal.aborted) return null;

        setState({ status: 'success', data });

        return data;
      } catch (error) {
        if (isAbortError(error) || controller.signal.aborted) return null;

        setState({
          status: 'error',
          message: routeErrorMessage(error),
          kind: error instanceof ApiError ? error.kind : 'unknown',
        });

        return null;
      } finally {
        if (controllerRef.current === controller) clearTimers();
      }
    },
    [clearTimers],
  );

  const reset = useCallback(() => {
    controllerRef.current?.abort();
    clearTimers();
    setState({ status: 'idle' });
  }, [clearTimers]);

  return { state, check, reset };
}
