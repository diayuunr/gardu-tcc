'use client';

import { useCallback, useEffect, useState } from 'react';

import { apiGet, errorMessage, isAbortError } from '@/lib/api';
import type { RiskHeatmap, RiskSummary } from '@/lib/api-types';
import type { TimeBucket } from '@/lib/risk';

interface BucketData {
  heatmap: RiskHeatmap;
  summary: RiskSummary | null;
  /** Pesan bila hanya ringkasan per kecamatan yang gagal (peta tetap tampil). */
  summaryError: string | null;
}

const TTL_MS = 60_000; // backend juga menyimpan cache 60 dtk
const cache = new Map<TimeBucket, { at: number; data: BucketData }>();

function fresh(bucket: TimeBucket): BucketData | null {
  const hit = cache.get(bucket);

  return hit && Date.now() - hit.at < TTL_MS ? hit.data : null;
}

/** Heatmap + ringkasan per kecamatan untuk satu bucket jam (dimuat bersamaan, bisa dibatalkan, di-cache singkat). */
export function useRiskData(bucket: TimeBucket) {
  const [result, setResult] = useState<{ bucket: TimeBucket; data: BucketData | null; error: string | null } | null>(
    null,
  );
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (fresh(bucket)) return;

    const controller = new AbortController();
    const options = { query: { time_bucket: bucket }, signal: controller.signal, timeoutMs: 15_000 };

    Promise.allSettled([
      apiGet<RiskHeatmap>('/risk/heatmap', options),
      apiGet<RiskSummary>('/risk/summary', options),
    ]).then(([heatmap, summary]) => {
      if (controller.signal.aborted) return;

      if (heatmap.status === 'rejected') {
        if (isAbortError(heatmap.reason)) return;

        setResult({ bucket, data: null, error: errorMessage(heatmap.reason, 'Data kerawanan belum dapat dimuat.') });
        return;
      }

      const data: BucketData = {
        heatmap: heatmap.value,
        summary: summary.status === 'fulfilled' ? summary.value : null,
        summaryError:
          summary.status === 'rejected'
            ? errorMessage(summary.reason, 'Ringkasan per kecamatan belum dapat dimuat.')
            : null,
      };

      if (data.summary) cache.set(bucket, { at: Date.now(), data });

      setResult({ bucket, data, error: null });
    });

    return () => controller.abort();
  }, [bucket, attempt]);

  const retry = useCallback(() => {
    cache.delete(bucket);
    setResult(null);
    setAttempt((value) => value + 1);
  }, [bucket]);

  const cached = fresh(bucket);
  const current = result?.bucket === bucket ? result : null;
  const data = cached ?? current?.data ?? null;

  return {
    data,
    loading: !cached && current === null,
    error: !cached ? (current?.error ?? null) : null,
    retry,
  };
}
