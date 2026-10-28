import type { PickedPlace } from '@/lib/geo';

/** Rute contoh (tempat populer DIY) untuk mencoba Cek Rute dengan cepat; jam = jam berangkat yang disarankan (WIB). */
export interface RouteExample {
  id: string;
  title: string;
  origin: PickedPlace;
  destination: PickedPlace;
  hour: number;
  hourLabel: string;
}

export const ROUTE_EXAMPLES: readonly RouteExample[] = [
  {
    id: 'sardjito-kaliurang',
    title: 'RSUP Sardjito ke Kaliurang',
    origin: { label: 'RSUP Dr. Sardjito', latitude: -7.7686, longitude: 110.3732 },
    destination: { label: 'Kaliurang', latitude: -7.6013, longitude: 110.426 },
    hour: 21,
    hourLabel: 'malam',
  },
  {
    id: 'prawirotaman-parangtritis',
    title: 'Prawirotaman ke Pantai Parangtritis',
    origin: { label: 'Prawirotaman', latitude: -7.8187, longitude: 110.3687 },
    destination: { label: 'Pantai Parangtritis', latitude: -8.025, longitude: 110.3288 },
    hour: 2,
    hourLabel: 'dini hari',
  },
  {
    id: 'jombor-sleman',
    title: 'Terminal Jombor ke Sleman City Hall',
    origin: { label: 'Terminal Jombor', latitude: -7.7472, longitude: 110.3616 },
    destination: { label: 'Sleman City Hall', latitude: -7.72018, longitude: 110.36191 },
    hour: 13,
    hourLabel: 'siang',
  },
];
