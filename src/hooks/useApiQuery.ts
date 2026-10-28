'use client';

import { useCallback, useEffect, useState } from 'react';

import { apiGet, errorMessage, isAbortError } from '@/lib/api';

type Query = Record<string, string | number>;

const TTL_MS = 30_000;
const cache = new Map<string, { at: number; data: unknown }>();

/** Buang hasil tersimpan yang path-nya berawalan `prefix` (mis. setelah laporan baru dikirim), supaya data berikutnya segar. */
export function invalidateApiCache(prefix: string): void {
  for (const key of [...cache.keys()]) {
    if (key.startsWith(prefix)) cache.delete(key);
  }
}

function fresh<T>(key: string): T | undefined {
  const hit = cache.get(key);

  return hit && Date.now() - hit.at < TTL_MS ? (hit.data as T) : undefined;
}

/**
 * GET bertipe dengan pembatalan, cache singkat per (path + query), dan muat ulang. `loading` diturunkan dari kunci
 * (tanpa setState sinkron di efek), jadi berpindah halaman/parameter langsung menampilkan keadaan memuat.
 */
export function useApiQuery<T>(path: string, query: Query = {}, fallbackError = 'Data belum dapat dimuat.') {
  const queryKey = JSON.stringify(query);
  const key = `${path}?${queryKey}`;

  const [result, setResult] = useState<{ key: string; data: T | null; error: string | null } | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (fresh<T>(key) !== undefined) return;

    const controller = new AbortController();

    apiGet<T>(path, { query: JSON.parse(queryKey) as Query, signal: controller.signal, timeoutMs: 15_000 })
      .then((data) => {
        cache.set(key, { at: Date.now(), data });
        setResult({ key, data, error: null });
      })
      .catch((error: unknown) => {
        if (isAbortError(error)) return;

        setResult({ key, data: null, error: errorMessage(error, fallbackError) });
      });

    return () => controller.abort();
  }, [key, path, queryKey, attempt, fallbackError]);

  const retry = useCallback(() => {
    cache.delete(key);
    setResult(null);
    setAttempt((value) => value + 1);
  }, [key]);

  const cached = fresh<T>(key);
  const current = result?.key === key ? result : null;

  return {
    data: cached ?? current?.data ?? null,
    loading: cached === undefined && current === null,
    error: cached === undefined ? (current?.error ?? null) : null,
    retry,
  };
}
