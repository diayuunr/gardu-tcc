/**
 * Logika murni Cek Rute (tanpa React/peta): menyusun tampilan rute utama + alternatif dari respons backend, GeoJSON per
 * ruas, batas peta, dan validasi isian. Dipisah supaya mudah diuji unit.
 */

import type { FeatureCollection, LineString } from 'geojson';

import type {
  GeoLineString,
  IncidentCategory,
  RouteCheck,
  RouteSegment,
} from '@/lib/api-types';
import { minutesFromNow, wibInputToIso, wibInputValue } from '@/lib/format';
import {
  BackendRiskLevel,
  RouteStatus,
  TIME_BUCKET_INFO,
  TimeBucket,
  timeBucketOfHour,
} from '@/lib/risk';
import type { PickedPlace } from '@/lib/geo';

/** Satu pilihan rute (utama atau alternatif) dengan bentuk seragam untuk panel dan peta. */
export interface RouteView {
  /** 0 = rute utama; i >= 1 = alternatif ke-i. */
  index: number;
  kind: 'main' | 'alternative';
  title: string;
  status: RouteStatus;
  maxScore: number;
  distanceKm: number;
  durationMinutes: number;
  dataCoverage: number;
  dataLimited: boolean;
  highExposureM: number;
  mediumExposureM: number;
  incidentCount: number;
  timeBuckets: TimeBucket[];
  segments: RouteSegment[];
  reasons: string[];
  geometry: GeoLineString;
  /** Selisih menit vs rute utama (hanya alternatif; negatif = lebih cepat). */
  extraMinutes: number | null;
  /** Backend menandai rute ini berisiko paling rendah di antara pilihan. */
  isLowestRisk: boolean;
}

export function buildRouteViews(check: RouteCheck): RouteView[] {
  const main: RouteView = {
    index: 0,
    kind: 'main',
    title: 'Rute utama',
    status: check.summary.status,
    maxScore: check.summary.max_risk_score,
    distanceKm: check.summary.distance_km,
    durationMinutes: check.summary.duration_minutes,
    dataCoverage: check.summary.data_coverage,
    dataLimited: check.summary.data_limited,
    highExposureM: check.summary.high_exposure_m,
    mediumExposureM: check.summary.medium_exposure_m,
    incidentCount: check.summary.incident_count,
    timeBuckets: check.summary.time_buckets,
    segments: check.segments,
    reasons: check.reasons,
    geometry: check.geometry,
    extraMinutes: null,
    isLowestRisk: check.recommended_route === 0,
  };

  const alternatives = check.alternatives.map<RouteView>((alt, position) => ({
    index: position + 1,
    kind: 'alternative',
    title: `Alternatif ${position + 1}`,
    status: alt.summary.status,
    maxScore: alt.summary.max_risk_score,
    distanceKm: alt.summary.distance_km,
    durationMinutes: alt.summary.duration_minutes,
    dataCoverage: alt.summary.data_coverage,
    dataLimited: alt.summary.data_limited,
    highExposureM: alt.summary.high_exposure_m,
    mediumExposureM: alt.summary.medium_exposure_m,
    incidentCount: alt.summary.incident_count,
    timeBuckets: alt.summary.time_buckets,
    segments: alt.segments,
    reasons: alt.reasons,
    geometry: alt.geometry,
    extraMinutes: alt.extra_minutes,
    isLowestRisk: alt.is_lowest_risk || check.recommended_route === position + 1,
  }));

  return [main, ...alternatives];
}

// ---------------------------------------------------------------------------
// GeoJSON dan batas peta ([bujur, lintang])
// ---------------------------------------------------------------------------

export type LngLat = [number, number];
export type Bounds = [LngLat, LngLat];

export function boundsOfCoordinates(coordinates: readonly LngLat[]): Bounds | null {
  const valid = coordinates.filter(
    ([lng, lat]) => Number.isFinite(lng) && Number.isFinite(lat),
  );

  if (valid.length === 0) return null;

  let west = Infinity;
  let south = Infinity;
  let east = -Infinity;
  let north = -Infinity;

  for (const [lng, lat] of valid) {
    west = Math.min(west, lng);
    east = Math.max(east, lng);
    south = Math.min(south, lat);
    north = Math.max(north, lat);
  }

  return [
    [west, south],
    [east, north],
  ];
}

export function mergeBounds(boxes: ReadonlyArray<Bounds | null>): Bounds | null {
  const present = boxes.filter((box): box is Bounds => box !== null);

  if (present.length === 0) return null;

  return boundsOfCoordinates(present.flat());
}

export function routeBounds(view: RouteView): Bounds | null {
  return boundsOfCoordinates(view.geometry.coordinates);
}

export function segmentBounds(segment: RouteSegment): Bounds | null {
  return boundsOfCoordinates(segment.geometry.coordinates);
}

/** Titik tengah (simpul tengah garis) sebuah ruas — dipakai untuk menaruh popup. */
export function segmentMidpoint(segment: RouteSegment): LngLat | null {
  const coords = segment.geometry.coordinates;

  if (coords.length === 0) return null;

  return coords[Math.floor((coords.length - 1) / 2)];
}

/** FeatureCollection satu fitur per ruas; properti `level`/`index` dipakai untuk mewarnai dan memilih. */
export function segmentsToFeatureCollection(
  segments: readonly RouteSegment[],
): FeatureCollection<LineString> {
  return {
    type: 'FeatureCollection',
    features: segments.map((segment) => ({
      type: 'Feature',
      geometry: { type: 'LineString', coordinates: segment.geometry.coordinates },
      properties: {
        index: segment.index,
        level: segment.risk_level,
        score: segment.risk_score,
      },
    })),
  };
}

/** Garis rute-rute lain (alternatif/utama yang tidak dipilih), satu fitur per rute. */
export function otherRoutesToFeatureCollection(
  views: readonly RouteView[],
  selectedIndex: number,
): FeatureCollection<LineString> {
  return {
    type: 'FeatureCollection',
    features: views
      .filter((view) => view.index !== selectedIndex)
      .map((view) => ({
        type: 'Feature',
        geometry: { type: 'LineString', coordinates: view.geometry.coordinates },
        properties: { routeIndex: view.index },
      })),
  };
}

// ---------------------------------------------------------------------------
// Teks
// ---------------------------------------------------------------------------

export const LEVEL_TITLE: Record<BackendRiskLevel, string> = {
  rendah: 'Rendah',
  sedang: 'Sedang',
  tinggi: 'Tinggi',
};

export function roadLabel(segment: Pick<RouteSegment, 'road_name'>): string {
  const name = segment.road_name?.trim();

  // Backend memberi "jalan tanpa nama" (huruf kecil) untuk ruas tak bernama.
  if (!name || name.toLowerCase() === 'jalan tanpa nama') return 'Jalan tanpa nama';

  return name;
}

/** "Malam 7 · Dini hari 2" (urut terbanyak); kosong bila tidak ada kejadian tercatat. */
export function describeIncidentHours(
  hours: Partial<Record<TimeBucket, number>>,
): string {
  return Object.entries(hours)
    .filter(([, count]) => typeof count === 'number' && count > 0)
    .sort((a, b) => (b[1] as number) - (a[1] as number))
    .map(([bucket, count]) => `${TIME_BUCKET_INFO[bucket as TimeBucket]?.label ?? bucket} ${count}`)
    .join(' · ');
}

export function categoryLabel(category: IncidentCategory | null): string | null {
  if (!category) return null;

  return category.charAt(0).toUpperCase() + category.slice(1);
}

// ---------------------------------------------------------------------------
// Isian formulir
// ---------------------------------------------------------------------------

/** Bucket jam dari isian waktu dinding WIB (YYYY-MM-DDTHH:mm); null bila tidak valid. */
export function bucketOfInput(value: string): TimeBucket | null {
  if (!wibInputToIso(value)) return null;

  return timeBucketOfHour(Number(value.slice(11, 13)));
}

/** Titik dianggap sama bila jaraknya < ~10 m (0,0001 derajat). */
export function samePoint(a: PickedPlace, b: PickedPlace): boolean {
  return (
    Math.abs(a.latitude - b.latitude) < 0.0001 && Math.abs(a.longitude - b.longitude) < 0.0001
  );
}

/** Batas backend: berangkat > 5 menit di masa lalu ditolak; maksimal 30 hari ke depan. */
export const MAX_PAST_MINUTES = 5;
export const MAX_FUTURE_DAYS = 30;

export interface RouteFormInput {
  origin: PickedPlace | null;
  destination: PickedPlace | null;
  /** null = berangkat sekarang. */
  departAt: string | null;
}

export interface RouteFormErrors {
  origin?: string;
  destination?: string;
  departAt?: string;
  form?: string;
}

export function validateRouteForm(input: RouteFormInput, now: Date = new Date()): RouteFormErrors {
  const errors: RouteFormErrors = {};

  if (!input.origin) errors.origin = 'Pilih titik asal dari saran, lokasi Anda, atau peta.';
  if (!input.destination) errors.destination = 'Pilih titik tujuan dari saran, lokasi Anda, atau peta.';

  if (input.origin && input.destination && samePoint(input.origin, input.destination)) {
    errors.form = 'Titik asal dan tujuan sama. Pilih dua titik yang berbeda.';
  }

  if (input.departAt !== null) {
    const diff = minutesFromNow(input.departAt, now);

    if (diff === null) {
      errors.departAt = 'Waktu berangkat belum valid. Isi tanggal dan jam.';
    } else if (diff < -MAX_PAST_MINUTES) {
      errors.departAt = 'Waktu berangkat tidak boleh di masa lalu.';
    } else if (diff > MAX_FUTURE_DAYS * 24 * 60) {
      errors.departAt = `Waktu berangkat maksimal ${MAX_FUTURE_DAYS} hari ke depan.`;
    }
  }

  return errors;
}

export function hasErrors(errors: RouteFormErrors): boolean {
  return Object.values(errors).some(Boolean);
}

/** Kunci perbandingan masukan, untuk menandai hasil "usang" bila titik/waktu berubah setelah pemeriksaan. */
export function requestKey(input: RouteFormInput): string {
  const point = (place: PickedPlace | null) =>
    place ? `${place.latitude.toFixed(5)},${place.longitude.toFixed(5)}` : '-';

  return `${point(input.origin)}|${point(input.destination)}|${input.departAt ?? 'sekarang'}`;
}

/**
 * Isian waktu WIB untuk kemunculan berikutnya jam `hour` (pukul hh.00) yang masih cukup ke depan
 * (>= `minAheadMinutes` dari sekarang); dipakai tombol "contoh rute".
 */
export function nextWibOccurrence(hour: number, now: Date = new Date(), minAheadMinutes = 5): string {
  const hh = String(hour).padStart(2, '0');
  const today = wibInputValue(now).slice(0, 10);
  const candidate = `${today}T${hh}:00`;
  const diff = minutesFromNow(candidate, now);

  if (diff !== null && diff >= minAheadMinutes) return candidate;

  const iso = wibInputToIso(candidate) as string;

  return wibInputValue(new Date(new Date(iso).getTime() + 24 * 60 * 60 * 1000));
}
