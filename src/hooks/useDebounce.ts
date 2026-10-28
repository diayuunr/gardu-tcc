'use client';

import { useEffect, useState } from 'react';

/** Nilai yang baru berubah setelah `delayMs` tanpa perubahan lagi (mis. 300 ms untuk kotak pencarian). */
export function useDebounce<T>(value: T, delayMs = 300): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);

    return () => clearTimeout(timer);
  }, [value, delayMs]);

  return debounced;
}
