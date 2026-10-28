/** Logika murni Peta Kerawanan: GeoJSON sel, batas peta, pengelompokan per kecamatan, dan penjaga nama kembar. */

import type { FeatureCollection, Point } from 'geojson';

import type { RegionRisk, RiskCell } from '@/lib/api-types';
import { BackendRiskLevel } from '@/lib/risk';
import { Bounds, boundsOfCoordinates } from '@/lib/route';

export function cellsToFeatureCollection(cells: readonly RiskCell[]): FeatureCollection<Point> {
  return {
    type: 'FeatureCollection',
    features: cells
      .filter(
        (cell) =>
          Number.isFinite(cell.latitude) && Number.isFinite(cell.longitude) && Number.isFinite(cell.risk_score),
      )
      .map((cell) => ({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [cell.longitude, cell.latitude] },
        properties: {
          label: cell.label,
          place: cell.place_name ?? '',
          score: cell.risk_score,
          level: cell.risk_level,
          count: cell.contributing_incident_count,
        },
      })),
  };
}

export function boundsOfCells(cells: readonly RiskCell[]): Bounds | null {
  return boundsOfCoordinates(cells.map((cell) => [cell.longitude, cell.latitude] as [number, number]));
}

/** Sel milik sebuah kecamatan (dicocokkan lewat `place_name`, yang sama dengan `place_name` ringkasan). */
export function cellsOfRegion(cells: readonly RiskCell[], region: Pick<RegionRisk, 'place_name'>): RiskCell[] {
  return cells.filter((cell) => cell.place_name === region.place_name);
}

/** Skor tertinggi dulu, lalu jumlah kejadian, lalu nama. */
export function sortCells(cells: readonly RiskCell[]): RiskCell[] {
  return [...cells].sort(
    (a, b) =>
      b.risk_score - a.risk_score ||
      b.contributing_incident_count - a.contributing_incident_count ||
      a.label.localeCompare(b.label, 'id'),
  );
}

/**
 * Daftar kecamatan tanpa duplikat: satu entri per kode kecamatan, dan label tampil dijamin unik
 * (bila dua kecamatan berlabel sama, kodenya ditambahkan). Backend sudah memberi keterangan pada nama kembar;
 * ini penjaga bila data berubah.
 */
export function uniqueRegions(regions: readonly RegionRisk[]): Array<RegionRisk & { displayLabel: string }> {
  const seenCodes = new Set<string>();
  const unique = regions.filter((region) => {
    if (seenCodes.has(region.kecamatan_kode)) return false;

    seenCodes.add(region.kecamatan_kode);

    return true;
  });

  const labelCount = new Map<string, number>();

  unique.forEach((region) => labelCount.set(region.label, (labelCount.get(region.label) ?? 0) + 1));

  return unique.map((region) => ({
    ...region,
    displayLabel: (labelCount.get(region.label) ?? 0) > 1 ? `${region.label} (${region.kecamatan_kode})` : region.label,
  }));
}

export function countByLevel(regions: readonly Pick<RegionRisk, 'risk_level'>[]): Record<BackendRiskLevel, number> {
  const counts: Record<BackendRiskLevel, number> = { rendah: 0, sedang: 0, tinggi: 0 };

  regions.forEach((region) => {
    counts[region.risk_level] += 1;
  });

  return counts;
}

export function totalIncidents(cells: readonly RiskCell[]): number {
  return cells.reduce((sum, cell) => sum + cell.contributing_incident_count, 0);
}
