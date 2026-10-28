/**
 * Pencarian tempat dan penentuan titik (GET /geo/search, GET /geo/reverse). Nilai yang dihasilkan komponen pemilih
 * tempat SELALU berupa PickedPlace {label, latitude, longitude}.
 *
 * PRIVASI: kata kunci dan koordinat hanya dikirim ke backend sebagai query; tidak pernah dicatat di konsol.
 */

import { ApiError, apiGet, isAbortError } from '@/lib/api';
import type { PlaceSearch, PlaceSource, ReverseGeocode } from '@/lib/api-types';

export interface PickedPlace {
  label: string;
  latitude: number;
  longitude: number;
}

/** Panjang minimal kata kunci (sesuai backend: 422 bila kurang dari 3 karakter). */
export const MIN_SEARCH_LENGTH = 3;

export const OUT_OF_DIY_MESSAGE =
  'Titik ini berada di luar wilayah D.I. Yogyakarta, sehingga tidak dapat dipakai. Pilih titik di dalam DIY.';

export const SOURCE_LABEL: Record<PlaceSource, string> = {
  landmark: 'Tempat populer',
  photon: 'OpenStreetMap',
  nominatim: 'OpenStreetMap',
  wilayah: 'Wilayah',
  mapbox: 'Mapbox',
};

export function searchPlaces(
  query: string,
  signal: AbortSignal,
  limit = 6,
): Promise<PlaceSearch> {
  return apiGet<PlaceSearch>('/geo/search', {
    query: { q: query, limit },
    signal,
    timeoutMs: 8_000,
  });
}

export function reversePoint(
  latitude: number,
  longitude: number,
  signal?: AbortSignal,
): Promise<ReverseGeocode> {
  return apiGet<ReverseGeocode>('/geo/reverse', {
    query: { lat: latitude, lon: longitude },
    signal,
    timeoutMs: 8_000,
  });
}

export type PointKind = 'gps' | 'map';

export interface ResolvedPoint {
  /** null bila titik di luar DIY (tidak dapat dipakai). */
  place: PickedPlace | null;
  outOfDiy: boolean;
  /** false bila nama wilayah gagal dimuat (titik tetap dipakai dengan label umum). */
  labelResolved: boolean;
}

const POINT_PREFIX: Record<PointKind, string> = {
  gps: 'Lokasi saya',
  map: 'Titik di peta',
};

/** Susun label tampil dari hasil /geo/reverse. */
export function labelForPoint(kind: PointKind, reverse: ReverseGeocode | null): string {
  const prefix = POINT_PREFIX[kind];

  if (!reverse || !reverse.kecamatan_kode) return prefix;

  return `${prefix} · ${reverse.label}`;
}

/**
 * Titik dari GPS atau klik peta -> tempat bernama lewat /geo/reverse. Titik di luar DIY ditolak (`place: null`).
 * Bila reverse gagal (jaringan/429/503), titik tetap dipakai dengan label umum; backend memvalidasi lagi saat rute diperiksa.
 * Pembatalan (AbortError) dilempar ulang.
 */
export async function placeFromPoint(
  latitude: number,
  longitude: number,
  kind: PointKind,
  signal?: AbortSignal,
): Promise<ResolvedPoint> {
  try {
    const reverse = await reversePoint(latitude, longitude, signal);

    if (!reverse.in_diy) {
      return { place: null, outOfDiy: true, labelResolved: true };
    }

    return {
      place: { label: labelForPoint(kind, reverse), latitude, longitude },
      outOfDiy: false,
      labelResolved: true,
    };
  } catch (error) {
    if (isAbortError(error)) throw error;

    if (!(error instanceof ApiError)) throw error;

    return {
      place: { label: labelForPoint(kind, null), latitude, longitude },
      outOfDiy: false,
      labelResolved: false,
    };
  }
}
