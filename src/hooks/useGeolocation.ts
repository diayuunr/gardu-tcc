'use client';

import { useCallback, useState } from 'react';

export type GeolocationStatus =
  | 'idle'
  | 'locating'
  | 'denied'
  | 'unavailable'
  | 'timeout'
  | 'error';

export interface GeoPoint {
  latitude: number;
  longitude: number;
}

const GEO_MESSAGES: Record<Exclude<GeolocationStatus, 'idle' | 'locating'>, string> = {
  denied:
    'Izin lokasi ditolak. Aktifkan izin lokasi di pengaturan peramban, atau cari tempat secara manual.',
  unavailable:
    'Lokasi Anda tidak dapat ditentukan saat ini. Cari tempat secara manual.',
  timeout: 'Pengambilan lokasi terlalu lama. Coba lagi atau cari tempat secara manual.',
  error: 'Lokasi tidak dapat diambil. Cari tempat secara manual.',
};

/** Kode galat Geolocation API -> status (1 = ditolak, 2 = tidak tersedia, 3 = waktu habis). */
export function geolocationStatusFromCode(code: number): GeolocationStatus {
  if (code === 1) return 'denied';
  if (code === 2) return 'unavailable';
  if (code === 3) return 'timeout';

  return 'error';
}

/**
 * Lokasi pengguna lewat `navigator.geolocation`, dengan penanganan izin ditolak / tidak tersedia / waktu habis.
 * PRIVASI: koordinat hanya diteruskan ke pemanggil; tidak disimpan, tidak dicatat.
 */
export function useGeolocation() {
  const [status, setStatus] = useState<GeolocationStatus>('idle');

  const locate = useCallback((): Promise<GeoPoint | null> => {
    if (typeof navigator === 'undefined' || !navigator.geolocation) {
      setStatus('unavailable');

      return Promise.resolve(null);
    }

    if (typeof window !== 'undefined' && !window.isSecureContext) {
      setStatus('error');

      return Promise.resolve(null);
    }

    setStatus('locating');

    return new Promise((resolve) => {
      navigator.geolocation.getCurrentPosition(
        (position) => {
          setStatus('idle');
          resolve({
            latitude: position.coords.latitude,
            longitude: position.coords.longitude,
          });
        },
        (failure) => {
          setStatus(geolocationStatusFromCode(failure.code));
          resolve(null);
        },
        { enableHighAccuracy: false, timeout: 10_000, maximumAge: 60_000 },
      );
    });
  }, []);

  const reset = useCallback(() => setStatus('idle'), []);

  const insecure =
    status === 'error' && typeof window !== 'undefined' && !window.isSecureContext;

  const message =
    status === 'idle' || status === 'locating'
      ? null
      : insecure
        ? 'Lokasi hanya dapat dipakai lewat koneksi aman (HTTPS). Cari tempat secara manual.'
        : GEO_MESSAGES[status];

  return { status, message, locating: status === 'locating', locate, reset };
}
