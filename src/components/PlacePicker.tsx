'use client';

import { useEffect, useId, useRef, useState } from 'react';
import { Crosshair, MapPin, Navigation, Search, X } from 'react-feather';

import { errorMessage, isAbortError } from '@/lib/api';
import type { PlaceHit } from '@/lib/api-types';
import {
  MIN_SEARCH_LENGTH,
  OUT_OF_DIY_MESSAGE,
  PickedPlace,
  SOURCE_LABEL,
  placeFromPoint,
  searchPlaces,
} from '@/lib/geo';
import { useDebounce } from '@/hooks/useDebounce';
import { useGeolocation } from '@/hooks/useGeolocation';

export type { PickedPlace } from '@/lib/geo';

const DEBOUNCE_MS = 300;

type SearchState = {
  query: string;
  hits: PlaceHit[];
  degraded: boolean;
  error: string | null;
};

/**
 * Pemilih tempat (combobox ARIA 1.2): saran otomatis dari GET /geo/search, "Lokasi saya" (GPS), dan "Pilih di peta".
 *
 * Nilai yang dihasilkan SELALU {label, latitude, longitude} (null bila belum ada pilihan). Mengetik mengosongkan
 * pilihan sampai pengguna memilih saran lagi. Titik GPS/peta di luar DIY ditolak dengan peringatan.
 * Pilihan di peta ditangani induk (peta ada di luar komponen ini): induk memberi `mapPickActive` dan
 * menerima `onRequestMapPick`, lalu mengisi `value` sendiri (pakai `placeFromPoint` dari '@/lib/geo').
 */
export default function PlacePicker({
  label,
  value,
  onChange,
  placeholder = 'Cari tempat, jalan, atau kampus',
  onRequestMapPick,
  mapPickActive = false,
  notice,
  error = null,
  disabled = false,
  allowGps = true,
  required = false,
  className = '',
}: {
  label: string;
  value: PickedPlace | null;
  onChange: (place: PickedPlace | null) => void;
  placeholder?: string;
  onRequestMapPick?: () => void;
  mapPickActive?: boolean;
  /** Catatan dari induk (mis. titik peta di luar DIY), ditampilkan di bawah kolom. */
  notice?: string | null;
  /** Galat validasi dari induk (mis. belum memilih titik), ditampilkan merah di bawah kolom. */
  error?: string | null;
  disabled?: boolean;
  allowGps?: boolean;
  required?: boolean;
  className?: string;
}) {
  const uid = useId();
  const inputId = `${uid}-input`;
  const listId = `${uid}-list`;

  const wrapperRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const gpsAbortRef = useRef<AbortController | null>(null);

  // Teks yang sedang diketik. `base` = nilai `value` saat mengetik; bila `value` berubah dari luar (tukar, GPS, peta),
  // draf otomatis tidak berlaku lagi tanpa efek samping.
  const [draft, setDraft] = useState<{ text: string; base: PickedPlace | null } | null>(null);
  const [open, setOpen] = useState(false);
  const [activeRaw, setActive] = useState(-1);
  const [search, setSearch] = useState<SearchState | null>(null);
  const [localNotice, setLocalNotice] = useState<string | null>(null);
  const [resolving, setResolving] = useState(false);

  const geo = useGeolocation();

  const typing = draft !== null && draft.base === value;
  const displayText = typing ? draft.text : (value?.label ?? '');
  const query = typing ? draft.text.trim() : '';
  const debounced = useDebounce(query, DEBOUNCE_MS);

  useEffect(() => {
    if (debounced.length < MIN_SEARCH_LENGTH) return;

    const controller = new AbortController();

    searchPlaces(debounced, controller.signal)
      .then((result) =>
        setSearch({ query: debounced, hits: result.results, degraded: result.degraded, error: null }),
      )
      .catch((error: unknown) => {
        if (isAbortError(error)) return;

        setSearch({
          query: debounced,
          hits: [],
          degraded: false,
          error: errorMessage(error, 'Pencarian tempat sedang bermasalah. Coba lagi.'),
        });
      });

    return () => controller.abort();
  }, [debounced]);

  useEffect(() => {
    const holder = gpsAbortRef;

    // Saat dilepas, batalkan reverse geocoding yang masih berjalan.
    return () => holder.current?.abort();
  }, []);

  const tooShort = query.length > 0 && query.length < MIN_SEARCH_LENGTH;
  const current = search && search.query === query && debounced === query ? search : null;
  const pending = query.length >= MIN_SEARCH_LENGTH && current === null;
  const hits = current?.hits ?? [];
  const searchError = current?.error ?? null;
  const expanded = open && typing && (tooShort || pending || current !== null);
  const active = activeRaw < hits.length ? activeRaw : -1;

  const announcement = !expanded
    ? ''
    : tooShort
      ? `Ketik minimal ${MIN_SEARCH_LENGTH} huruf untuk mencari.`
      : pending
        ? 'Mencari saran tempat.'
        : searchError
          ? searchError
          : hits.length > 0
            ? `${hits.length} saran tersedia. Gunakan tombol panah atas dan bawah, lalu Enter untuk memilih.`
            : 'Tidak ada saran yang cocok.';

  function choose(hit: PlaceHit) {
    setDraft(null);
    setOpen(false);
    setActive(-1);
    setLocalNotice(null);
    geo.reset();
    onChange({ label: hit.label, latitude: hit.latitude, longitude: hit.longitude });
  }

  function handleInput(text: string) {
    setDraft({ text, base: null });
    setOpen(true);
    setActive(-1);
    setLocalNotice(null);
    geo.reset();

    if (value !== null) onChange(null);
  }

  function clear() {
    setDraft(null);
    setOpen(false);
    setActive(-1);
    setLocalNotice(null);
    geo.reset();
    onChange(null);
    inputRef.current?.focus();
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      if (!typing || hits.length === 0) return;

      event.preventDefault();
      setOpen(true);

      const step = event.key === 'ArrowDown' ? 1 : -1;

      setActive(active < 0 ? (step > 0 ? 0 : hits.length - 1) : (active + step + hits.length) % hits.length);
      return;
    }

    if (event.key === 'Enter') {
      if (expanded && active >= 0) {
        event.preventDefault();
        choose(hits[active]);
      }

      return;
    }

    if (event.key === 'Escape') {
      if (expanded) {
        event.preventDefault();
        setOpen(false);
        setActive(-1);
      } else if (displayText) {
        event.preventDefault();
        clear();
      }
    }
  }

  function handleBlur(event: React.FocusEvent<HTMLDivElement>) {
    if (!wrapperRef.current?.contains(event.relatedTarget as Node | null)) {
      setOpen(false);
      setActive(-1);
    }
  }

  async function useMyLocation() {
    setLocalNotice(null);
    setOpen(false);

    const point = await geo.locate();

    if (!point) return;

    gpsAbortRef.current?.abort();

    const controller = new AbortController();

    gpsAbortRef.current = controller;
    setResolving(true);

    try {
      const result = await placeFromPoint(point.latitude, point.longitude, 'gps', controller.signal);

      if (result.outOfDiy || !result.place) {
        setLocalNotice(OUT_OF_DIY_MESSAGE);
        return;
      }

      setDraft(null);
      onChange(result.place);

      if (!result.labelResolved) {
        setLocalNotice('Nama wilayah belum dapat dimuat, tetapi titik lokasi Anda tetap dipakai.');
      }
    } catch (error) {
      if (!isAbortError(error)) setLocalNotice('Lokasi Anda belum dapat diproses. Coba lagi.');
    } finally {
      if (gpsAbortRef.current === controller) setResolving(false);
    }
  }

  const shownNotice = notice ?? localNotice ?? geo.message;
  const busy = geo.locating || resolving;
  const showSpinner = pending && expanded;

  return (
    <div ref={wrapperRef} onBlur={handleBlur} className={`relative ${className}`}>
      <label htmlFor={inputId} className="mb-2 block text-sm font-medium text-zinc-300">
        {label}
        {required && (
          <span className="ml-1 text-emerald-400" aria-hidden="true">
            *
          </span>
        )}
      </label>

      <div className="relative">
        <Search
          size={16}
          className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-zinc-500"
          aria-hidden="true"
        />

        <input
          ref={inputRef}
          id={inputId}
          type="text"
          role="combobox"
          aria-expanded={expanded}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={expanded && active >= 0 ? `${listId}-opt-${active}` : undefined}
          aria-required={required}
          aria-invalid={error ? true : undefined}
          aria-describedby={
            [error ? `${uid}-error` : null, shownNotice ? `${uid}-notice` : null].filter(Boolean).join(' ') || undefined
          }
          aria-busy={busy || showSpinner}
          autoComplete="off"
          autoCorrect="off"
          spellCheck={false}
          disabled={disabled}
          placeholder={placeholder}
          value={displayText}
          onChange={(event) => handleInput(event.target.value)}
          onFocus={() => setOpen(true)}
          onKeyDown={handleKeyDown}
          className="input pl-11 pr-11"
        />

        <div className="absolute right-2 top-1/2 flex -translate-y-1/2 items-center">
          {showSpinner || busy ? (
            <span
              className="mr-2 h-4 w-4 animate-spin rounded-full border-2 border-emerald-400/30 border-t-emerald-400 motion-reduce:animate-none"
              aria-hidden="true"
            />
          ) : null}

          {displayText && !disabled && (
            <button
              type="button"
              onClick={clear}
              className="rounded-full p-2 text-zinc-500 transition hover:text-zinc-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400/60"
              aria-label={`Hapus ${label.toLowerCase()}`}
            >
              <X size={16} aria-hidden="true" />
            </button>
          )}
        </div>

        {expanded && (
          <ul
            id={listId}
            role="listbox"
            aria-label={`Saran untuk ${label.toLowerCase()}`}
            className="absolute left-0 right-0 top-full z-30 mt-2 max-h-72 overflow-y-auto rounded-2xl border border-line bg-panel p-1.5 shadow-2xl shadow-black/50"
          >
            {tooShort && (
              <li role="presentation" className="px-3 py-3 text-sm text-zinc-500">
                Ketik minimal {MIN_SEARCH_LENGTH} huruf untuk mencari.
              </li>
            )}

            {pending && !tooShort && (
              <li role="presentation" className="px-3 py-3 text-sm text-zinc-500">
                Mencari...
              </li>
            )}

            {searchError && (
              <li role="presentation" className="px-3 py-3 text-sm text-amber-300">
                {searchError}
              </li>
            )}

            {hits.map((hit, index) => {
              const selected = index === active;

              return (
                <li
                  key={`${hit.source}-${hit.latitude}-${hit.longitude}-${hit.label}`}
                  id={`${listId}-opt-${index}`}
                  role="option"
                  aria-selected={selected}
                  onMouseDown={(event) => event.preventDefault()}
                  onMouseEnter={() => setActive(index)}
                  onClick={() => choose(hit)}
                  className={`flex cursor-pointer items-start gap-3 rounded-xl px-3 py-2.5 ${
                    selected ? 'bg-emerald-400/10' : 'hover:bg-white/5'
                  }`}
                >
                  <MapPin size={16} className="mt-0.5 shrink-0 text-emerald-400" aria-hidden="true" />

                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium text-zinc-100">{hit.label}</span>

                    {hit.place_name && hit.place_name !== hit.label && (
                      <span className="block truncate text-xs text-zinc-500">{hit.place_name}</span>
                    )}
                  </span>

                  <span className="mt-0.5 shrink-0 rounded-full border border-line px-2 py-0.5 text-[10px] uppercase tracking-wide text-zinc-500">
                    {SOURCE_LABEL[hit.source]}
                  </span>
                </li>
              );
            })}

            {!tooShort && !pending && !searchError && hits.length === 0 && (
              <li role="presentation" className="px-3 py-3 text-sm text-zinc-500">
                Tempat tidak ditemukan. Coba nama jalan, kampus, atau kecamatan.
              </li>
            )}

            {current?.degraded && (
              <li role="presentation" className="px-3 pb-2 pt-1 text-[11px] text-zinc-600">
                Sebagian sumber pencarian sedang terganggu, hasil mungkin kurang lengkap.
              </li>
            )}
          </ul>
        )}
      </div>

      {(allowGps || onRequestMapPick) && (
        <div className="mt-2 flex flex-wrap gap-2">
          {allowGps && (
            <button
              type="button"
              onClick={useMyLocation}
              disabled={disabled || busy}
              className="inline-flex items-center gap-1.5 rounded-full border border-line px-3 py-1.5 text-xs font-medium text-zinc-300 transition hover:border-emerald-400/40 hover:text-emerald-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400/60 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Navigation size={13} aria-hidden="true" />
              {geo.locating ? 'Mencari lokasi...' : 'Lokasi saya'}
            </button>
          )}

          {onRequestMapPick && (
            <button
              type="button"
              onClick={onRequestMapPick}
              disabled={disabled}
              aria-pressed={mapPickActive}
              className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400/60 disabled:cursor-not-allowed disabled:opacity-50 ${
                mapPickActive
                  ? 'border-emerald-400/60 bg-emerald-400/10 text-emerald-300'
                  : 'border-line text-zinc-300 hover:border-emerald-400/40 hover:text-emerald-300'
              }`}
            >
              <Crosshair size={13} aria-hidden="true" />
              {mapPickActive ? 'Klik titik di peta...' : 'Pilih di peta'}
            </button>
          )}
        </div>
      )}

      {error && (
        <p id={`${uid}-error`} role="alert" className="mt-2 text-xs leading-relaxed text-red-300">
          {error}
        </p>
      )}

      {shownNotice && (
        <p id={`${uid}-notice`} role="status" className="mt-2 text-xs leading-relaxed text-amber-300">
          {shownNotice}
        </p>
      )}

      <div className="sr-only" aria-live="polite" aria-atomic="true">
        {announcement}
      </div>
    </div>
  );
}
