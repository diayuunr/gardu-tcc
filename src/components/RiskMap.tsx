'use client';

import { useEffect, useRef } from 'react';
import type {
  GeoJSONSource,
  Map as MapboxMap,
  MapMouseEvent,
} from 'mapbox-gl';
import type {
  FeatureCollection,
  Point,
  Feature,
} from 'geojson';

import 'mapbox-gl/dist/mapbox-gl.css';

import { RiskPoint } from '@/lib/types';

type RiskMapProps = {
  points: RiskPoint[];
};

/*
|--------------------------------------------------------------------------
| KONFIGURASI PETA
|--------------------------------------------------------------------------
*/

const YOGYAKARTA_CENTER: [number, number] = [
  110.3695,
  -7.7956,
];

const MAX_BOUNDS: [
  [number, number],
  [number, number],
] = [
  [109.9, -8.35],
  [110.95, -7.4],
];

/*
|--------------------------------------------------------------------------
| LAYER ID
|--------------------------------------------------------------------------
*/

const SOURCE_ID = 'risk-points';

const HEAT_LAYER_ID = 'risk-heatmap';

const CIRCLE_LAYER_ID = 'risk-circles';

const LABEL_LAYER_ID = 'risk-labels';

/*
|--------------------------------------------------------------------------
| WARNA
|--------------------------------------------------------------------------
|
| Tetap mengikuti konsep risk:
|
| rendah  → hijau
| sedang  → kuning/oranye
| tinggi  → merah
|
*/

const RISK_COLORS = {
  rendah: '#4c8c6b',
  sedang: '#d4a24c',
  tinggi: '#b85c4c',
};

/*
|--------------------------------------------------------------------------
| CONVERT RiskPoint → GeoJSON
|--------------------------------------------------------------------------
*/

function toGeoJson(
  points: RiskPoint[],
): FeatureCollection<Point> {
  return {
    type: 'FeatureCollection',

    features: points.map((point) => ({
      type: 'Feature',

      geometry: {
        type: 'Point',

        coordinates: [
          point.lng,
          point.lat,
        ],
      },

      properties: {
        area_name: point.area_name,

        score: point.score,

        level: point.level,
      },
    })),
  };
}

/*
|--------------------------------------------------------------------------
| VALIDASI POINT
|--------------------------------------------------------------------------
*/

function getValidPoints(
  points: RiskPoint[],
) {
  return points.filter(
    (point) =>
      Number.isFinite(point.lat) &&
      Number.isFinite(point.lng) &&
      Number.isFinite(point.score),
  );
}

/*
|--------------------------------------------------------------------------
| FIT MAP KE DATA
|--------------------------------------------------------------------------
*/

function fitToPoints(
  map: MapboxMap,
  points: RiskPoint[],
  animate = false,
) {
  if (points.length === 0) {
    map.flyTo({
      center: YOGYAKARTA_CENTER,
      zoom: 10.5,
      duration: animate ? 600 : 0,
    });

    return;
  }

  /*
   * Satu titik
   */

  if (points.length === 1) {
    const point = points[0];

    map.flyTo({
      center: [
        point.lng,
        point.lat,
      ],

      zoom: 13,

      duration: animate ? 600 : 0,
    });

    return;
  }

  /*
   * Banyak titik
   */

  const lons = points.map(
    (point) => point.lng,
  );

  const lats = points.map(
    (point) => point.lat,
  );

  const bounds: [
    [number, number],
    [number, number],
  ] = [
    [
      Math.min(...lons),
      Math.min(...lats),
    ],

    [
      Math.max(...lons),
      Math.max(...lats),
    ],
  ];

  map.fitBounds(bounds, {
    padding: 70,

    maxZoom: 13,

    duration: animate ? 600 : 0,
  });
}

/*
|--------------------------------------------------------------------------
| COMPONENT
|--------------------------------------------------------------------------
*/

export default function RiskMap({
  points,
}: RiskMapProps) {
  const containerRef =
    useRef<HTMLDivElement | null>(null);

  const mapRef =
    useRef<MapboxMap | null>(null);

  /*
   * Data terbaru disimpan di ref supaya
   * event click tidak perlu membuat ulang map.
   */

  const pointsRef =
    useRef<RiskPoint[]>(points);

  /*
   * UPDATE REF DATA
   */

  useEffect(() => {
    pointsRef.current = points;
  }, [points]);

  /*
  |--------------------------------------------------------------------------
  | INITIALIZE MAP
  |--------------------------------------------------------------------------
  */

  useEffect(() => {
    let cancelled = false;

    async function initMap() {
      if (!containerRef.current) {
        return;
      }

      if (mapRef.current) {
        return;
      }

      /*
       * Token
       */

      const token =
        process.env.NEXT_PUBLIC_MAPBOX_TOKEN;

      if (!token) {
        console.error(
          'NEXT_PUBLIC_MAPBOX_TOKEN belum di-set.',
        );

        return;
      }

      /*
       * Import Mapbox
       */

      const mapboxgl =
        (await import('mapbox-gl')).default;

      if (cancelled) {
        return;
      }

      /*
       * Set token
       */

      mapboxgl.accessToken = token;

      /*
       * Buat map
       */

      const map = new mapboxgl.Map({
        container:
          containerRef.current,

        /*
         * DARK MAP
         */

        style:
          'mapbox://styles/mapbox/dark-v11',

        center:
          YOGYAKARTA_CENTER,

        zoom: 10,

        maxBounds:
          MAX_BOUNDS,

        minZoom: 9,

        maxZoom: 17,

        dragRotate: false,

        pitchWithRotate: false,

        attributionControl: true,
      });

      /*
       * Navigation control
       */

      map.addControl(
        new mapboxgl.NavigationControl({
          showCompass: false,
        }),
        'top-right',
      );

      /*
       * Simpan instance
       */

      mapRef.current = map;

      /*
       * LOAD
       */

      map.on('load', () => {
        if (cancelled) {
          return;
        }

        /*
         * ============================================
         * SOURCE
         * ============================================
         */

        map.addSource(
          SOURCE_ID,
          {
            type: 'geojson',

            data: toGeoJson(
              getValidPoints(
                pointsRef.current,
              ),
            ),
          },
        );

        /*
         * ============================================
         * HEATMAP
         * ============================================
         */

        map.addLayer({
          id: HEAT_LAYER_ID,

          type: 'heatmap',

          source: SOURCE_ID,

          paint: {
            /*
             * SCORE 0–100
             *
             * 0    → 0
             * 100  → 1
             */

            'heatmap-weight': [
              'interpolate',
              ['linear'],
              ['get', 'score'],

              0,
              0,

              25,
              0.25,

              50,
              0.5,

              75,
              0.75,

              100,
              1,
            ],

            /*
             * Intensitas berdasarkan zoom.
             */

            'heatmap-intensity': [
              'interpolate',
              ['linear'],
              ['zoom'],

              9,
              1.5,

              12,
              2.5,

              15,
              4,
            ],

            /*
             * WARNA HEATMAP
             *
             * rendah
             *   ↓
             * hijau
             *   ↓
             * kuning
             *   ↓
             * orange
             *   ↓
             * merah
             */

            'heatmap-color': [
              'interpolate',
              ['linear'],
              ['heatmap-density'],

              0,
              'rgba(76,140,107,0)',

              0.15,
              'rgba(76,140,107,0.35)',

              0.3,
              'rgba(212,162,76,0.55)',

              0.5,
              'rgba(212,162,76,0.75)',

              0.7,
              'rgba(242,166,90,0.85)',

              0.85,
              'rgba(184,92,76,0.92)',

              1,
              'rgba(127,29,29,0.98)',
            ],

            /*
             * Radius berubah mengikuti zoom.
             *
             * Zoom kecil:
             * heatmap lebih luas
             *
             * Zoom besar:
             * lebih detail.
             */

            'heatmap-radius': [
              'interpolate',
              ['linear'],
              ['zoom'],

              9,
              30,

              11,
              45,

              13,
              70,

              15,
              110,
            ],

            /*
             * Sedikit transparan ketika zoom sangat dekat
             * supaya circle tetap terlihat.
             */

            'heatmap-opacity': [
              'interpolate',
              ['linear'],
              ['zoom'],

              9,
              0.9,

              12,
              0.85,

              15,
              0.55,
            ],
          },
        });

        /*
         * ============================================
         * CIRCLE
         * ============================================
         *
         * Titik tetap terlihat.
         */

        map.addLayer({
          id: CIRCLE_LAYER_ID,

          type: 'circle',

          source: SOURCE_ID,

          paint: {
            /*
             * Ukuran circle mengikuti zoom.
             */

            'circle-radius': [
              'interpolate',
              ['linear'],
              ['zoom'],

              9,
              4,

              12,
              6,

              15,
              10,
            ],

            /*
             * Warna berdasarkan level
             */

            'circle-color': [
              'interpolate',
              ['linear'],
              ['get', 'score'],

              0,
              '#4c8c6b',

              25,
              '#4c8c6b',

              50,
              '#d4a24c',

              75,
              '#f2a65a',

              100,
              '#b85c4c',
            ],
            'circle-stroke-color':
              '#e8e6e1',

            'circle-stroke-width': 1.5,

            'circle-opacity': 0.95,

            'circle-stroke-opacity': 0.9,
          },
        });

        /*
         * ============================================
         * LABEL AREA
         * ============================================
         *
         * Hanya muncul ketika zoom cukup dekat.
         */

        map.addLayer({
          id: LABEL_LAYER_ID,

          type: 'symbol',

          source: SOURCE_ID,

          minzoom: 11,

          layout: {
            'text-field': [
              'get',
              'area_name',
            ],

            'text-size': [
              'interpolate',
              ['linear'],
              ['zoom'],

              11,
              10,

              14,
              13,
            ],

            'text-offset': [
              0,
              1.4,
            ],

            'text-anchor':
              'top',

            'text-allow-overlap':
              false,
          },

          paint: {
            'text-color':
              '#e8e6e1',

            'text-halo-color':
              '#111827',

            'text-halo-width':
              1.5,

            'text-opacity': [
              'interpolate',
              ['linear'],
              ['zoom'],

              11,
              0.6,

              13,
              1,
            ],
          },
        });

        /*
         * ============================================
         * CLICK
         * ============================================
         */

        map.on(
          'click',
          CIRCLE_LAYER_ID,
          (
            event: MapMouseEvent,
          ) => {
            const feature =
              event.features?.[0];

            if (!feature) {
              return;
            }

            const properties =
              feature.properties;

            if (!properties) {
              return;
            }

            const area =
              properties.area_name ??
              'Area';

            const score =
              Number(
                properties.score ?? 0,
              );

            const level =
              properties.level ??
              'rendah';

            /*
             * Popup Mapbox
             */

            new mapboxgl.Popup({
              closeButton: true,

              closeOnClick: true,

              offset: 12,
            })
              .setLngLat(
                event.lngLat,
              )
              .setHTML(`
                <div style="
                  min-width: 180px;
                  font-family: Inter, sans-serif;
                  color: #111827;
                ">
                  <div style="
                    font-size: 10px;
                    font-weight: 600;
                    letter-spacing: 0.15em;
                    text-transform: uppercase;
                    color: #6b7280;
                    margin-bottom: 5px;
                  ">
                    AREA KERAWANAN
                  </div>

                  <div style="
                    font-size: 16px;
                    font-weight: 700;
                    margin-bottom: 10px;
                  ">
                    ${area}
                  </div>

                  <div style="
                    display: flex;
                    justify-content: space-between;
                    gap: 16px;
                    font-size: 13px;
                  ">
                    <span>
                      Risiko
                    </span>

                    <strong>
                      ${level}
                    </strong>
                  </div>

                  <div style="
                    display: flex;
                    justify-content: space-between;
                    gap: 16px;
                    margin-top: 4px;
                    font-size: 13px;
                  ">
                    <span>
                      Skor
                    </span>

                    <strong>
                      ${score.toFixed(0)}
                    </strong>
                  </div>
                </div>
              `)
              .addTo(map);
          },
        );

        /*
         * Cursor pointer
         */

        map.on(
          'mouseenter',
          CIRCLE_LAYER_ID,
          () => {
            map.getCanvas().style.cursor =
              'pointer';
          },
        );

        map.on(
          'mouseleave',
          CIRCLE_LAYER_ID,
          () => {
            map.getCanvas().style.cursor =
              '';
          },
        );

        /*
         * ============================================
         * FOCUS KE DATA
         * ============================================
         */

        const validPoints =
          getValidPoints(
            pointsRef.current,
          );

        fitToPoints(
          map,
          validPoints,
          false,
        );
      });
    }

    void initMap();

    /*
     * CLEANUP
     */

    return () => {
      cancelled = true;

      if (mapRef.current) {
        mapRef.current.remove();

        mapRef.current = null;
      }
    };
  }, []);

  /*
  |--------------------------------------------------------------------------
  | UPDATE DATA
  |--------------------------------------------------------------------------
  */

  useEffect(() => {
    const map =
      mapRef.current;

    if (!map) {
      return;
    }

    if (!map.isStyleLoaded()) {
      return;
    }

    const source =
      map.getSource(
        SOURCE_ID,
      ) as GeoJSONSource | undefined;

    if (!source) {
      return;
    }

    /*
     * Validasi
     */

    const validPoints =
      getValidPoints(points);

    /*
     * Update source
     */

    source.setData(
      toGeoJson(
        validPoints,
      ),
    );

    /*
     * Fokus ulang
     */

    const reduceMotion =
      window.matchMedia(
        '(prefers-reduced-motion: reduce)',
      ).matches;

    fitToPoints(
      map,
      validPoints,
      !reduceMotion,
    );
  }, [points]);

  /*
  |--------------------------------------------------------------------------
  | RENDER
  |--------------------------------------------------------------------------
  */

  return (
    <div
      ref={containerRef}
      role="region"
      aria-label="Peta kerawanan Yogyakarta"
      className="
        h-[540px]
        w-full
        overflow-hidden
        rounded-3xl
        border
        border-white/10
        shadow-glow
      "
    />
  );
}