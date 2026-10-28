'use client';

import { useEffect, useRef, useState } from 'react';
import type { FeatureCollection, LineString } from 'geojson';
import type { GeoJSONSource, Map as MapboxMap, Marker, Popup } from 'mapbox-gl';

import 'mapbox-gl/dist/mapbox-gl.css';

import type { PickedPlace } from '@/lib/geo';
import {
  DIY_CENTER,
  DIY_MAX_BOUNDS,
  HAS_MAPBOX_TOKEN,
  MAPBOX_TOKEN,
  MAP_STYLE,
  prefersReducedMotion,
} from '@/lib/mapbox';
import { LEVEL_HEX } from '@/lib/risk';
import {
  Bounds,
  RouteView,
  boundsOfCoordinates,
  otherRoutesToFeatureCollection,
  routeBounds,
  segmentBounds,
  segmentMidpoint,
  segmentsToFeatureCollection,
} from '@/lib/route';
import { buildSegmentPopup } from '@/components/route/segmentPopup';

export type PickTarget = 'origin' | 'destination';
export type MapStatus = 'loading' | 'ready' | 'no-token' | 'failed';

const SRC_SEGMENTS = 'route-segments';
const SRC_OTHERS = 'route-others';
const LAYER_CASING = 'route-casing';
const LAYER_HIGHLIGHT = 'route-highlight';
const LAYER_LINE = 'route-line';
const LAYER_HIT = 'route-hit';
const LAYER_OTHERS = 'route-others-line';
const LAYER_OTHERS_HIT = 'route-others-hit';

const EMPTY: FeatureCollection<LineString> = { type: 'FeatureCollection', features: [] };

const PICK_LABEL: Record<PickTarget, string> = { origin: 'asal', destination: 'tujuan' };

function markerElement(letter: string, className: string, label: string): HTMLElement {
  const element = document.createElement('div');

  element.className = `flex h-8 w-8 items-center justify-center rounded-full border-2 border-white text-xs font-bold shadow-lg shadow-black/60 ${className}`;
  element.textContent = letter;
  element.setAttribute('role', 'img');
  element.setAttribute('aria-label', label);

  return element;
}

/**
 * Peta rute (Mapbox GL, gaya gelap): rute terpilih digambar RUAS DEMI RUAS berwarna menurut tingkat risiko, rute lain
 * lebih tipis dan abu-abu, penanda A/B, klik ruas membuka popup, dan mode "pilih titik di peta".
 * Tanpa token / gagal memuat: menampilkan pesan, bukan layar kosong.
 */
export default function RouteMap({
  origin,
  destination,
  views,
  selectedIndex,
  onSelectRoute,
  focusedSegment,
  onFocusSegment,
  pickTarget,
  onPickPoint,
  onCancelPick,
  resolvingPick = false,
  onStatusChange,
  className = '',
}: {
  origin: PickedPlace | null;
  destination: PickedPlace | null;
  views: RouteView[] | null;
  selectedIndex: number;
  onSelectRoute: (index: number) => void;
  focusedSegment: number | null;
  /** Indeks ruas yang dipilih di peta; null = popup ditutup pengguna. */
  onFocusSegment: (segmentIndex: number | null) => void;
  pickTarget: PickTarget | null;
  onPickPoint: (latitude: number, longitude: number) => void;
  onCancelPick: () => void;
  resolvingPick?: boolean;
  onStatusChange?: (status: MapStatus) => void;
  className?: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapboxMap | null>(null);
  const mapboxRef = useRef<typeof import('mapbox-gl').default | null>(null);
  const markersRef = useRef<{ origin?: Marker; destination?: Marker }>({});
  const popupRef = useRef<Popup | null>(null);
  const lastFitRef = useRef<string>('');

  const [status, setStatus] = useState<MapStatus>(HAS_MAPBOX_TOKEN ? 'loading' : 'no-token');
  const [attempt, setAttempt] = useState(0);

  // Props terbaru untuk penangan peristiwa peta (dibuat sekali), tanpa membuat ulang peta.
  const latest = useRef({ pickTarget, onPickPoint, onSelectRoute, onFocusSegment });

  useEffect(() => {
    latest.current = { pickTarget, onPickPoint, onSelectRoute, onFocusSegment };
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
          zoom: 10,
          minZoom: 8.5,
          maxZoom: 18,
          maxBounds: DIY_MAX_BOUNDS,
          dragRotate: false,
          pitchWithRotate: false,
          attributionControl: true,
        });
      } catch {
        // Mis. WebGL tidak didukung peramban.
        setStatus('failed');
        return;
      }

      mapRef.current = map;
      map.addControl(new mapboxgl.NavigationControl({ showCompass: false }), 'top-right');

      let loaded = false;

      map.on('error', () => {
        // Galat sebelum gaya selesai dimuat (token salah/jaringan) = peta tidak bisa dipakai.
        if (!loaded && !cancelled) setStatus('failed');
      });

      map.on('load', () => {
        if (cancelled) return;

        loaded = true;

        map.addSource(SRC_OTHERS, { type: 'geojson', data: EMPTY });
        map.addSource(SRC_SEGMENTS, { type: 'geojson', data: EMPTY });

        map.addLayer({
          id: LAYER_OTHERS,
          type: 'line',
          source: SRC_OTHERS,
          layout: { 'line-cap': 'round', 'line-join': 'round' },
          paint: { 'line-color': '#94a3b8', 'line-width': 4, 'line-opacity': 0.75, 'line-dasharray': [1.5, 1.2] },
        });
        map.addLayer({
          id: LAYER_OTHERS_HIT,
          type: 'line',
          source: SRC_OTHERS,
          paint: { 'line-color': '#000000', 'line-width': 22, 'line-opacity': 0.01 },
        });
        map.addLayer({
          id: LAYER_CASING,
          type: 'line',
          source: SRC_SEGMENTS,
          layout: { 'line-cap': 'round', 'line-join': 'round' },
          paint: { 'line-color': '#030806', 'line-width': 11, 'line-opacity': 0.9 },
        });
        map.addLayer({
          id: LAYER_HIGHLIGHT,
          type: 'line',
          source: SRC_SEGMENTS,
          filter: ['==', ['get', 'index'], -1],
          layout: { 'line-cap': 'round', 'line-join': 'round' },
          paint: { 'line-color': '#ffffff', 'line-width': 15, 'line-opacity': 0.4, 'line-blur': 2 },
        });
        map.addLayer({
          id: LAYER_LINE,
          type: 'line',
          source: SRC_SEGMENTS,
          layout: { 'line-cap': 'round', 'line-join': 'round' },
          paint: {
            'line-color': [
              'match',
              ['get', 'level'],
              'tinggi',
              LEVEL_HEX.tinggi,
              'sedang',
              LEVEL_HEX.sedang,
              LEVEL_HEX.rendah,
            ],
            'line-width': 6.5,
          },
        });
        map.addLayer({
          id: LAYER_HIT,
          type: 'line',
          source: SRC_SEGMENTS,
          paint: { 'line-color': '#000000', 'line-width': 24, 'line-opacity': 0.01 },
        });

        for (const layer of [LAYER_HIT, LAYER_OTHERS_HIT]) {
          map.on('mouseenter', layer, () => {
            if (!latest.current.pickTarget) map.getCanvas().style.cursor = 'pointer';
          });
          map.on('mouseleave', layer, () => {
            map.getCanvas().style.cursor = latest.current.pickTarget ? 'crosshair' : '';
          });
        }

        map.on('click', (event) => {
          const { pickTarget: target, onPickPoint: pick, onSelectRoute: select, onFocusSegment: focus } = latest.current;

          if (target) {
            pick(event.lngLat.lat, event.lngLat.lng);
            return;
          }

          const segmentHit = map.queryRenderedFeatures(event.point, { layers: [LAYER_HIT] })[0];

          if (segmentHit) {
            focus(Number(segmentHit.properties?.index));
            return;
          }

          const otherHit = map.queryRenderedFeatures(event.point, { layers: [LAYER_OTHERS_HIT] })[0];

          if (otherHit) select(Number(otherHit.properties?.routeIndex));
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
      const popup = popupRef.current;

      popupRef.current = null;
      popup?.remove();
      Object.values(markersRef.current).forEach((marker) => marker?.remove());
      markersRef.current = {};
      mapRef.current?.remove();
      mapRef.current = null;
      lastFitRef.current = '';
    };
  }, [attempt]);

  // --------------------------------------------------------------------- data
  const selected = views?.find((view) => view.index === selectedIndex) ?? views?.[0] ?? null;

  useEffect(() => {
    const map = mapRef.current;

    if (status !== 'ready' || !map) return;

    (map.getSource(SRC_SEGMENTS) as GeoJSONSource | undefined)?.setData(
      selected ? segmentsToFeatureCollection(selected.segments) : EMPTY,
    );
    (map.getSource(SRC_OTHERS) as GeoJSONSource | undefined)?.setData(
      views && selected ? otherRoutesToFeatureCollection(views, selected.index) : EMPTY,
    );
  }, [status, views, selected]);

  // ----------------------------------------------------------------- penanda
  useEffect(() => {
    const map = mapRef.current;
    const mapboxgl = mapboxRef.current;

    if (status !== 'ready' || !map || !mapboxgl) return;

    const wanted: Array<[keyof typeof markersRef.current, PickedPlace | null, string, string, string]> = [
      ['origin', origin, 'A', 'bg-sky-400 text-sky-950', 'Titik asal'],
      ['destination', destination, 'B', 'bg-violet-400 text-violet-950', 'Titik tujuan'],
    ];

    for (const [key, place, letter, color, label] of wanted) {
      const existing = markersRef.current[key];

      if (!place) {
        existing?.remove();
        markersRef.current[key] = undefined;
        continue;
      }

      if (existing) {
        existing.setLngLat([place.longitude, place.latitude]);
      } else {
        markersRef.current[key] = new mapboxgl.Marker({ element: markerElement(letter, color, label) })
          .setLngLat([place.longitude, place.latitude])
          .addTo(map);
      }
    }
  }, [status, origin, destination]);

  // ------------------------------------------------------------------ viewport
  useEffect(() => {
    const map = mapRef.current;

    if (status !== 'ready' || !map) return;

    const narrow = (containerRef.current?.clientWidth ?? 800) < 560;
    const padding = narrow ? 36 : 70;
    const animate = !prefersReducedMotion();

    let bounds: Bounds | null = null;
    let key = '';

    if (selected) {
      bounds = routeBounds(selected);
      key = `route:${selected.index}:${selected.geometry.coordinates.length}:${selected.distanceKm}`;
    } else if (origin && destination) {
      bounds = boundsOfCoordinates([
        [origin.longitude, origin.latitude],
        [destination.longitude, destination.latitude],
      ]);
      key = `pair:${origin.latitude},${origin.longitude}|${destination.latitude},${destination.longitude}`;
    } else if (origin || destination) {
      const place = (origin ?? destination) as PickedPlace;

      key = `one:${place.latitude},${place.longitude}`;

      if (lastFitRef.current !== key) {
        lastFitRef.current = key;
        map.flyTo({ center: [place.longitude, place.latitude], zoom: 13, animate });
      }

      return;
    }

    if (!bounds || lastFitRef.current === key) return;

    lastFitRef.current = key;
    map.fitBounds(bounds, { padding, maxZoom: 16, animate, duration: 900 });
  }, [status, selected, origin, destination]);

  // ------------------------------------------------------- ruas terpilih (popup)
  useEffect(() => {
    const map = mapRef.current;
    const mapboxgl = mapboxRef.current;

    if (status !== 'ready' || !map || !mapboxgl) return;

    const previous = popupRef.current;

    popupRef.current = null; // dilepas lebih dulu supaya penutupan programatik tidak dianggap klik "tutup" pengguna
    previous?.remove();
    map.setFilter(LAYER_HIGHLIGHT, ['==', ['get', 'index'], focusedSegment ?? -1]);

    const segment = focusedSegment === null ? undefined : selected?.segments.find((s) => s.index === focusedSegment);

    if (!segment) return;

    const bounds = segmentBounds(segment);
    const middle = segmentMidpoint(segment);

    if (bounds) {
      map.fitBounds(bounds, { padding: 70, maxZoom: 15.5, animate: !prefersReducedMotion(), duration: 700 });
    }

    if (middle) {
      const popup = new mapboxgl.Popup({ className: 'gardu-popup', closeButton: true, offset: 10, maxWidth: '260px' })
        .setLngLat(middle)
        .setDOMContent(buildSegmentPopup(segment))
        .addTo(map);

      popup.on('close', () => {
        if (popupRef.current === popup) {
          popupRef.current = null;
          latest.current.onFocusSegment(null);
        }
      });
      popupRef.current = popup;
    }
  }, [status, focusedSegment, selected]);

  // ------------------------------------------------------------ mode pilih titik
  useEffect(() => {
    const map = mapRef.current;

    if (status === 'ready' && map) map.getCanvas().style.cursor = pickTarget ? 'crosshair' : '';

    if (!pickTarget) return;

    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onCancelPick();
    };

    window.addEventListener('keydown', onKey);

    return () => window.removeEventListener('keydown', onKey);
  }, [status, pickTarget, onCancelPick]);

  // ------------------------------------------------------------------- tampilan
  return (
    <div className={`relative overflow-hidden rounded-3xl border border-line bg-ink ${className}`}>
      {/* mapbox-gl.css memaksa position:relative pada .mapboxgl-map dan menimpa `absolute`;
          tanpa tinggi eksplisit elemen runtuh jadi 0 px, jadi ukuran diberi lewat h/w-full. */}
      <div ref={containerRef} className="h-full w-full" aria-label="Peta rute" />

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
              Pemeriksaan rute tetap bisa dipakai: hasilnya ditampilkan sebagai daftar ruas jalan di panel.
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

      {pickTarget && status === 'ready' && (
        <div className="absolute inset-x-3 top-3 z-10 flex items-center justify-between gap-3 rounded-2xl border border-emerald-400/40 bg-panel/95 px-4 py-3 shadow-xl backdrop-blur" role="status">
          <p className="text-sm text-zinc-200">
            {resolvingPick
              ? 'Memeriksa lokasi...'
              : `Ketuk peta untuk menentukan titik ${PICK_LABEL[pickTarget]}.`}
          </p>
          <button type="button" className="shrink-0 text-xs font-semibold text-emerald-300 underline-offset-2 hover:underline" onClick={onCancelPick}>
            Batal
          </button>
        </div>
      )}

      {selected && status === 'ready' && (
        <div className="pointer-events-none absolute bottom-6 left-3 z-10 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border border-line bg-panel/90 px-3 py-2 text-[11px] text-zinc-300 backdrop-blur" aria-hidden="true">
          {(['rendah', 'sedang', 'tinggi'] as const).map((level) => (
            <span key={level} className="inline-flex items-center gap-1.5">
              <span className="h-1.5 w-4 rounded-full" style={{ background: LEVEL_HEX[level] }} />
              {level.charAt(0).toUpperCase() + level.slice(1)}
            </span>
          ))}
          {views && views.length > 1 && (
            <span className="inline-flex items-center gap-1.5">
              <span className="h-0 w-4 border-t-2 border-dashed border-slate-400" />
              Rute lain
            </span>
          )}
        </div>
      )}
    </div>
  );
}
