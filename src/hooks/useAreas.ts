'use client';

import { useCallback, useEffect, useState } from 'react';

import { apiGet, errorMessage, isAbortError } from '@/lib/api';
import type { Area, AreaLevel, AreaList } from '@/lib/api-types';

// Data wilayah praktis statis: simpan per sesi agar dropdown tidak memuat ulang.
const cache = new Map<string, Area[]>();

/**
 * Daftar wilayah dari GET /areas (kabkota -> kecamatan -> kelurahan). `parent` null/'' pada tingkat bawah = tidak
 * dimuat. Mendukung pembatalan, cache, dan muat ulang saat gagal.
 */
export function useAreas(tingkat: AreaLevel, parent: string | null) {
  const enabled = tingkat === 'kabkota' || Boolean(parent);
  const key = enabled ? `${tingkat}|${parent ?? ''}` : null;

  const [result, setResult] = useState<{ key: string; areas: Area[]; error: string | null } | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!key || cache.has(key)) return;

    const controller = new AbortController();

    apiGet<AreaList>('/areas', {
      query: { tingkat, parent: parent ?? undefined },
      signal: controller.signal,
    })
      .then((response) => {
        cache.set(key, response.areas);
        setResult({ key, areas: response.areas, error: null });
      })
      .catch((error: unknown) => {
        if (isAbortError(error)) return;

        setResult({ key, areas: [], error: errorMessage(error, 'Daftar wilayah belum dapat dimuat.') });
      });

    return () => controller.abort();
  }, [key, tingkat, parent, attempt]);

  const cached = key ? cache.get(key) : undefined;
  const current = key !== null && result?.key === key ? result : null;

  const retry = useCallback(() => {
    setResult(null);
    setAttempt((value) => value + 1);
  }, []);

  return {
    areas: cached ?? current?.areas ?? [],
    loading: key !== null && !cached && current === null,
    error: !cached && current ? current.error : null,
    retry,
  };
}
