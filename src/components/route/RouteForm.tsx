'use client';

import { Repeat, Search } from 'react-feather';

import PlacePicker, { PickedPlace } from '@/components/PlacePicker';
import { TIME_BUCKET_INFO } from '@/lib/risk';
import { ROUTE_EXAMPLES, RouteExample } from '@/lib/route-examples';
import { RouteFormErrors, bucketOfInput } from '@/lib/route';
import type { PickTarget } from '@/components/route/RouteMap';

export type TimeMode = 'now' | 'custom';

export interface PickNotice {
  target: PickTarget;
  text: string;
}

/** Formulir Cek Rute: dua pemilih tempat (ketik / GPS / peta), tukar, waktu berangkat, dan contoh rute. */
export default function RouteForm({
  origin,
  destination,
  onOriginChange,
  onDestinationChange,
  onSwap,
  pickTarget,
  onTogglePick,
  pickNotice,
  timeMode,
  onTimeModeChange,
  departAt,
  onDepartAtChange,
  minDepart,
  narrative,
  onNarrativeChange,
  errors,
  loading,
  onSubmit,
  onExample,
}: {
  origin: PickedPlace | null;
  destination: PickedPlace | null;
  onOriginChange: (place: PickedPlace | null) => void;
  onDestinationChange: (place: PickedPlace | null) => void;
  onSwap: () => void;
  pickTarget: PickTarget | null;
  /** undefined = pilih-di-peta tidak tersedia (peta tidak dimuat). */
  onTogglePick?: (target: PickTarget) => void;
  pickNotice: PickNotice | null;
  timeMode: TimeMode;
  onTimeModeChange: (mode: TimeMode) => void;
  departAt: string;
  onDepartAtChange: (value: string) => void;
  minDepart: string;
  narrative: boolean;
  onNarrativeChange: (value: boolean) => void;
  errors: RouteFormErrors;
  loading: boolean;
  onSubmit: () => void;
  onExample: (example: RouteExample) => void;
}) {
  const bucket = timeMode === 'custom' ? bucketOfInput(departAt) : null;

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
      className="glass-card space-y-5 p-5 sm:p-6"
      noValidate
    >
      <PlacePicker
        label="Titik asal"
        value={origin}
        onChange={onOriginChange}
        placeholder="Mis. UGM, Stasiun Tugu, Jalan Kaliurang"
        onRequestMapPick={onTogglePick ? () => onTogglePick('origin') : undefined}
        mapPickActive={pickTarget === 'origin'}
        notice={pickNotice?.target === 'origin' ? pickNotice.text : null}
        error={errors.origin}
        disabled={loading}
        required
      />

      <div className="flex items-center gap-3" aria-hidden={false}>
        <span className="h-px flex-1 bg-line" aria-hidden="true" />
        <button
          type="button"
          onClick={onSwap}
          disabled={loading || (!origin && !destination)}
          className="inline-flex items-center gap-2 rounded-full border border-line px-3 py-1.5 text-xs font-medium text-zinc-300 transition hover:border-emerald-400/40 hover:text-emerald-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400/60 disabled:cursor-not-allowed disabled:opacity-40"
          aria-label="Tukar titik asal dan tujuan"
        >
          <Repeat size={13} aria-hidden="true" />
          Tukar
        </button>
        <span className="h-px flex-1 bg-line" aria-hidden="true" />
      </div>

      <PlacePicker
        label="Titik tujuan"
        value={destination}
        onChange={onDestinationChange}
        placeholder="Mis. Malioboro, Bandara YIA, Parangtritis"
        onRequestMapPick={onTogglePick ? () => onTogglePick('destination') : undefined}
        mapPickActive={pickTarget === 'destination'}
        notice={pickNotice?.target === 'destination' ? pickNotice.text : null}
        error={errors.destination}
        disabled={loading}
        allowGps={false}
        required
      />

      <fieldset className="space-y-2" disabled={loading}>
        <legend className="mb-2 block text-sm font-medium text-zinc-300">Waktu berangkat (WIB)</legend>

        <div className="inline-flex rounded-full border border-line p-1" role="group" aria-label="Pilih waktu berangkat">
          {(
            [
              ['now', 'Sekarang'],
              ['custom', 'Atur waktu'],
            ] as const
          ).map(([mode, text]) => (
            <button
              key={mode}
              type="button"
              aria-pressed={timeMode === mode}
              onClick={() => onTimeModeChange(mode)}
              className={`rounded-full px-4 py-1.5 text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400/60 ${
                timeMode === mode ? 'bg-emerald-400 text-emerald-950' : 'text-zinc-400 hover:text-zinc-200'
              }`}
            >
              {text}
            </button>
          ))}
        </div>

        {timeMode === 'custom' && (
          <div>
            <label htmlFor="rute-waktu" className="sr-only">
              Tanggal dan jam berangkat (WIB)
            </label>
            <input
              id="rute-waktu"
              type="datetime-local"
              className="input"
              value={departAt}
              min={minDepart}
              onChange={(event) => onDepartAtChange(event.target.value)}
              aria-invalid={errors.departAt ? true : undefined}
              aria-describedby="rute-waktu-info"
            />
          </div>
        )}

        <p id="rute-waktu-info" className="text-xs leading-relaxed text-zinc-500">
          {bucket
            ? `Jam ${TIME_BUCKET_INFO[bucket].label.toLowerCase()} (${TIME_BUCKET_INFO[bucket].range} WIB): risiko dinilai menurut jam ini.`
            : 'Risiko dinilai menurut jam keberangkatan dan jam tiba di tiap bagian jalur.'}
        </p>

        {errors.departAt && (
          <p role="alert" className="text-xs text-red-300">
            {errors.departAt}
          </p>
        )}
      </fieldset>

      <label className="flex cursor-pointer items-start gap-3 text-sm text-zinc-400">
        <input
          type="checkbox"
          checked={narrative}
          onChange={(event) => onNarrativeChange(event.target.checked)}
          disabled={loading}
          className="mt-0.5 h-4 w-4 shrink-0 accent-emerald-400"
        />
        <span>
          Tambahkan ringkasan AI <span className="text-zinc-600">(opsional, membuat pemeriksaan lebih lama)</span>
        </span>
      </label>

      {errors.form && (
        <p role="alert" className="text-sm text-red-300">
          {errors.form}
        </p>
      )}

      <button type="submit" className="btn-primary w-full disabled:cursor-not-allowed disabled:opacity-60" disabled={loading}>
        {loading ? (
          <>
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-emerald-950/30 border-t-emerald-950 motion-reduce:animate-none" aria-hidden="true" />
            Memeriksa...
          </>
        ) : (
          <>
            <Search size={16} aria-hidden="true" />
            Periksa Risiko Rute
          </>
        )}
      </button>

      <div className="border-t border-line pt-4">
        <p className="mb-2 text-xs font-semibold uppercase tracking-[0.2em] text-zinc-500">Coba contoh rute</p>

        <div className="flex flex-wrap gap-2">
          {ROUTE_EXAMPLES.map((example) => (
            <button
              key={example.id}
              type="button"
              onClick={() => onExample(example)}
              disabled={loading}
              className="rounded-full border border-line px-3 py-1.5 text-left text-xs text-zinc-300 transition hover:border-emerald-400/40 hover:text-emerald-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400/60 disabled:opacity-50"
            >
              {example.title} <span className="text-zinc-500">· {example.hourLabel}</span>
            </button>
          ))}
        </div>
      </div>
    </form>
  );
}
