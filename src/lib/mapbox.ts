/**
 * Konfigurasi Mapbox sisi peramban. Token HARUS token publik (pk.*) milik proyek ini; tanpa token, peta tidak dimuat dan
 * halaman menampilkan pesan serta fallback daftar.
 */

export const MAPBOX_TOKEN = process.env.NEXT_PUBLIC_MAPBOX_TOKEN ?? '';

export const HAS_MAPBOX_TOKEN = MAPBOX_TOKEN.length > 0;

export const MAP_STYLE = 'mapbox://styles/mapbox/dark-v11';

/** Pusat dan batas wilayah D.I. Yogyakarta ([bujur, lintang]). */
export const DIY_CENTER: [number, number] = [110.3695, -7.7956];

export const DIY_MAX_BOUNDS: [[number, number], [number, number]] = [
  [109.9, -8.4],
  [110.95, -7.4],
];

export function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}
