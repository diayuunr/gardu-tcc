'use client';

import { useEffect, useRef, useState } from 'react';
import type { ExpressionSpecification, GeoJSONSource, Map as MapboxMap, Popup } from 'mapbox-gl';
import type { FeatureCollection, Point } from 'geojson';

import 'mapbox-gl/dist/mapbox-gl.css';

import { buildCellPopup } from '@/components/risk/cellPopup';
import type { RiskCell } from '@/lib/api-types';
import {
  DIY_CENTER,
  DIY_MAX_BOUNDS,
  HAS_MAPBOX_TOKEN,
  MAPBOX_TOKEN,
  MAP_STYLE,
  prefersReducedMotion,
} from '@/lib/mapbox';
import { BackendRiskLevel, LEVEL_HEX } from '@/lib/risk';
import { boundsOfCells, cellsOfRegion, cellsToFeatureCollection } from '@/lib/riskmap';

export type RiskMapStatus = 'loading' | 'ready' | 'no-token' | 'failed';

const SOURCE = 'risk-cells';
const L_HEAT = 'risk-heat';
const L_CIRCLE = 'risk-circles';
const L_NEIGHBOR = 'risk-circles-neighbor';
const L_HIGHLIGHT = 'risk-highlight';

const EMPTY: FeatureCollection<Point> = { type: 'FeatureCollection', features: [] };

/**
 * Peta kerawanan: heatmap saat jauh, lingkaran per sel (ukuran mengikuti sel ±1 km) saat didekatkan, diwarnai menurut
 * level. PENTING: wadah peta harus punya tinggi eksplisit dari induk, dan elemen peta memakai h-full w-full
 * (mapbox-gl.css memaksa position:relative sehingga `absolute inset-0` tidak berlaku).
 */
export default function RiskHeatMap({
  cells,
  bucketLabel,
  highlightPlace,
  onStatusChange,
  className = '',
}: {
  cells: RiskCell[];
  bucketLabel: string;
  /** place_name kecamatan yang disorot (sel-selnya diberi garis putih dan peta difokuskan ke sana). */
  highlightPlace: string | null;
  onStatusChange?: (status: RiskMapStatus) => void;
  /** Wajib memuat tinggi eksplisit (mis. h-[60vh]). */
  className?: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapboxMap | null>(null);
  const mapboxRef = useRef<typeof import('mapbox-gl').default | null>(null);
  const popupRef = useRef<Popup | null>(null);
  const labelRef = useRef(bucketLabel);

  const [status, setStatus] = useState<RiskMapStatus>(HAS_MAPBOX_TOKEN ? 'loading' : 'no-token');
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    labelRef.current = bucketLabel;
  });

  useEffect(() => {
    onStatusChange?.(status);
  }, [status, onStatusChange]);

  // ---------------------------------------------------------------- inisialisasi
  useEffect(() => {
    if (!HAS_MAPBOX_TOKEN) return;

    let cancelled = false;
    let resizeObserver: ResizeObserver | null = null;

    async function init() {
      const container = containerRef.current;

      if (!container || mapRef.current) return;

      let mapboxgl: typeof import('mapbox-gl').default;

      try {
        mapboxgl = (await import('mapbox-gl')).default;
      } catch {
        if (!cancelled) setStatus('failed');
        return;
      }

      if (cancelled) return;

      mapboxgl.accessToken = MAPBOX_TOKEN;
      mapboxRef.current = mapboxgl;

      let map: MapboxMap;

      try {
        map = new mapboxgl.Map({
          container,
          style: MAP_STYLE,
          center: DIY_CENTER,
          zoom: 9.6,
          minZoom: 8.5,
          maxZoom: 16,
          maxBounds: DIY_MAX_BOUNDS,
          dragRotate: false,
          pitchWithRotate: false,
        });
      } catch {
        setStatus('failed');
        return;
      }

      mapRef.current = map;
      map.addControl(new mapboxgl.NavigationControl({ showCompass: false }), 'top-right');

      let loaded = false;

      map.on('error', () => {
        if (!loaded && !cancelled) setStatus('failed');
      });

      map.on('load', () => {
        if (cancelled) return;

        loaded = true;
        map.addSource(SOURCE, { type: 'geojson', data: EMPTY });

        const levelColor: ExpressionSpecification = [
          'match',
          ['get', 'level'],
          'tinggi',
          LEVEL_HEX.tinggi,
          'sedang',
          LEVEL_HEX.sedang,
          LEVEL_HEX.rendah,
        ];

        map.addLayer({
          id: L_HEAT,
          type: 'heatmap',
          source: SOURCE,
          paint: {
            'heatmap-weight': ['interpolate', ['linear'], ['get', 'score'], 0, 0, 10, 1],
            'heatmap-intensity': ['interpolate', ['linear'], ['zoom'], 9, 1, 13, 2],
            'heatmap-radius': ['interpolate', ['linear'], ['zoom'], 9, 18, 13, 60],
            'heatmap-color': [
              'interpolate',
              ['linear'],
              ['heatmap-density'],
              0,
              'rgba(52,211,153,0)',
              0.2,
              'rgba(52,211,153,0.35)',
              0.5,
              'rgba(251,191,36,0.6)',
              0.8,
              'rgba(248,113,113,0.8)',
              1,
              'rgba(248,113,113,0.95)',
            ],
            'heatmap-opacity': ['interpolate', ['linear'], ['zoom'], 9, 0.9, 12, 0.7, 14, 0],
          },
        });

        const radius: ExpressionSpecification = [
          'interpolate',
          ['exponential', 2],
          ['zoom'],
          9,
          9,
          11.5,
          10.5,
          12,
          14.7,
          17,
          470,
        ];

        // Lingkaran per sel HANYA untuk sel yang punya kejadian sendiri (count > 0): ±550 m, minimal 9 px agar mudah disentuh.
        map.addLayer({
          id: L_CIRCLE,
          type: 'circle',
          source: SOURCE,
          filter: ['>', ['get', 'count'], 0],
          paint: {
            'circle-color': levelColor,
            'circle-radius': radius,
            'circle-opacity': ['interpolate', ['linear'], ['zoom'], 9, 0.18, 12, 0.5],
            'circle-stroke-color': levelColor,
            'circle-stroke-width': 1,
            'circle-stroke-opacity': 0.85,
          },
        });

        // Sel tetangga (count = 0, skor hanya "tumpahan" dari sel sekitar): cukup ikut heatmap halus; lingkarannya
        // baru muncul samar pada zoom tinggi dan tetap bisa diklik.
        map.addLayer({
          id: L_NEIGHBOR,
          type: 'circle',
          source: SOURCE,
          minzoom: 12.5,
          filter: ['==', ['get', 'count'], 0],
          paint: {
            'circle-color': levelColor,
            'circle-radius': radius,
            'circle-opacity': ['interpolate', ['linear'], ['zoom'], 12.5, 0, 14, 0.12],
            'circle-stroke-color': levelColor,
            'circle-stroke-width': 1,
            'circle-stroke-opacity': ['interpolate', ['linear'], ['zoom'], 12.5, 0, 14, 0.3],
          },
        });

        map.addLayer({
          id: L_HIGHLIGHT,
          type: 'circle',
          source: SOURCE,
          filter: ['==', ['get', 'place'], '\u0000'],
          paint: {
            'circle-color': 'rgba(255,255,255,0.0)',
            'circle-radius': ['interpolate', ['exponential', 2], ['zoom'], 9, 11, 11.5, 12.5, 12, 16.5, 17, 480],
            'circle-stroke-color': '#ffffff',
            'circle-stroke-width': 2,
          },
        });

        for (const layer of [L_CIRCLE, L_NEIGHBOR]) {
          map.on('mouseenter', layer, () => {
            map.getCanvas().style.cursor = 'pointer';
          });
          map.on('mouseleave', layer, () => {
            map.getCanvas().style.cursor = '';
          });
        }

        map.on('click', [L_CIRCLE, L_NEIGHBOR], (event) => {
          const feature = event.features?.[0];

          if (!feature || feature.geometry.type !== 'Point') return;

          const props = feature.properties ?? {};

          popupRef.current?.remove();
          popupRef.current = new mapboxgl.Popup({ className: 'gardu-popup', offset: 8, maxWidth: '260px' })
            .setLngLat(feature.geometry.coordinates as [number, number])
            .setDOMContent(
              buildCellPopup(
                {
                  label: String(props.label),
                  level: props.level as BackendRiskLevel,
                  score: Number(props.score),
                  count: Number(props.count),
                },
                labelRef.current,
              ),
            )
            .addTo(map);
        });

        setStatus('ready');
      });

      resizeObserver = new ResizeObserver(() => map.resize());
      resizeObserver.observe(container);
    }

    void init();

    return () => {
      cancelled = true;
      resizeObserver?.disconnect();
      popupRef.current?.remove();
      popupRef.current = null;
      mapRef.current?.remove();
      mapRef.current = null;
    };
  }, [attempt]);

  // ----------------------------------------------- data (hanya setelah gaya selesai dimuat)
  useEffect(() => {
    const map = mapRef.current;

    if (status !== 'ready' || !map) return;

    popupRef.current?.remove();
    popupRef.current = null;
    (map.getSource(SOURCE) as GeoJSONSource | undefined)?.setData(cellsToFeatureCollection(cells));
  }, [status, cells]);

  // ----------------------------------------------------------- viewport + sorotan
  useEffect(() => {
    const map = mapRef.current;

    if (status !== 'ready' || !map) return;

    map.setFilter(L_HIGHLIGHT, ['==', ['get', 'place'], highlightPlace ?? '\u0000']);

    const target = highlightPlace ? cellsOfRegion(cells, { place_name: highlightPlace }) : cells;
    const bounds = boundsOfCells(target);

    if (!bounds) {
      map.easeTo({ center: DIY_CENTER, zoom: 9.6, animate: !prefersReducedMotion() });
      return;
    }

    map.fitBounds(bounds, {
      padding: (containerRef.current?.clientWidth ?? 800) < 560 ? 36 : 64,
      maxZoom: highlightPlace ? 13.5 : 12,
      animate: !prefersReducedMotion(),
      duration: 800,
    });
  }, [status, cells, highlightPlace]);

  return (
    <div className={`relative overflow-hidden rounded-3xl border border-line bg-ink ${className}`}>
      {/* mapbox-gl.css memaksa position:relative pada .mapboxgl-map dan menimpa `absolute`;
          tinggi berasal dari wadah di atas, jadi pakai h-full w-full (jangan diganti absolute inset-0). */}
      <div ref={containerRef} className="h-full w-full" aria-label="Peta kerawanan" />

      {status === 'loading' && (
        <div className="absolute inset-0 flex items-center justify-center bg-ink/80" role="status">
          <div className="flex items-center gap-3 text-sm text-zinc-400">
            <span className="h-5 w-5 animate-spin rounded-full border-2 border-emerald-400/30 border-t-emerald-400 motion-reduce:animate-none" />
            Memuat peta...
          </div>
        </div>
      )}

      {(status === 'no-token' || status === 'failed') && (
        <div className="absolute inset-0 flex items-center justify-center bg-ink p-6" role="alert">
          <div className="max-w-sm text-center">
            <p className="font-display text-lg font-semibold text-white">Peta belum dapat ditampilkan</p>
            <p className="mt-2 text-sm leading-relaxed text-zinc-400">
              {status === 'no-token'
                ? 'Token peta (NEXT_PUBLIC_MAPBOX_TOKEN) belum diisi.'
                : 'Peta gagal dimuat. Periksa koneksi internet atau token peta.'}{' '}
              Data kerawanan tetap tersedia pada tabel di bawah.
            </p>

            {status === 'failed' && (
              <button
                type="button"
                className="btn-ghost mt-4 !px-5 !py-2"
                onClick={() => {
                  setStatus('loading');
                  setAttempt((value) => value + 1);
                }}
              >
                Coba muat ulang peta
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
