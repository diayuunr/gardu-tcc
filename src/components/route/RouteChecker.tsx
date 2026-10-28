'use client';

import dynamic from 'next/dynamic';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import RouteForm, { PickNotice, TimeMode } from '@/components/route/RouteForm';
import type { MapStatus, PickTarget } from '@/components/route/RouteMap';
import RouteResultPanel from '@/components/route/RouteResultPanel';
import { RouteErrorPanel, RouteIdlePanel, RouteLoadingPanel } from '@/components/route/RouteStatusPanels';
import { useRouteCheck } from '@/hooks/useRouteCheck';
import { isAbortError } from '@/lib/api';
import type { RouteCheckBody } from '@/lib/api-types';
import { wibInputToIso, wibInputValue } from '@/lib/format';
import { OUT_OF_DIY_MESSAGE, PickedPlace, placeFromPoint } from '@/lib/geo';
import { HAS_MAPBOX_TOKEN, prefersReducedMotion } from '@/lib/mapbox';
import {
  RouteFormErrors,
  buildRouteViews,
  hasErrors,
  nextWibOccurrence,
  requestKey,
  validateRouteForm,
} from '@/lib/route';
import type { RouteExample } from '@/lib/route-examples';

const RouteMap = dynamic(() => import('@/components/route/RouteMap'), {
  ssr: false,
  loading: () => (
    <div className="flex h-full w-full items-center justify-center rounded-3xl border border-line bg-ink" role="status">
      <span className="h-6 w-6 animate-spin rounded-full border-2 border-emerald-400/30 border-t-emerald-400 motion-reduce:animate-none" />
      <span className="sr-only">Memuat peta</span>
    </div>
  ),
});

/** Halaman Cek Rute: formulir + peta berwarna per ruas + panel hasil. Mobile: peta di atas, panel di bawah. */
export default function RouteChecker() {
  const { state, check } = useRouteCheck();

  const [origin, setOrigin] = useState<PickedPlace | null>(null);
  const [destination, setDestination] = useState<PickedPlace | null>(null);
  const [timeMode, setTimeMode] = useState<TimeMode>('now');
  const [departAt, setDepartAt] = useState('');
  const [minDepart, setMinDepart] = useState('');
  const [narrative, setNarrative] = useState(false);
  const [errors, setErrors] = useState<RouteFormErrors>({});

  const [pickTarget, setPickTarget] = useState<PickTarget | null>(null);
  const [pickNotice, setPickNotice] = useState<PickNotice | null>(null);
  const [resolvingPick, setResolvingPick] = useState(false);
  const [mapStatus, setMapStatus] = useState<MapStatus>(HAS_MAPBOX_TOKEN ? 'loading' : 'no-token');

  const [selectedRoute, setSelectedRoute] = useState(0);
  const [focusedSegment, setFocusedSegment] = useState<number | null>(null);
  const [submittedKey, setSubmittedKey] = useState<string | null>(null);
  const [submittedLabels, setSubmittedLabels] = useState({ origin: '', destination: '' });

  const mapSectionRef = useRef<HTMLDivElement>(null);
  const resultRef = useRef<HTMLDivElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const pickAbortRef = useRef<AbortController | null>(null);

  const mapUsable = mapStatus === 'loading' || mapStatus === 'ready';
  const loading = state.status === 'loading';

  const views = useMemo(
    () => (state.status === 'success' ? buildRouteViews(state.data) : null),
    [state],
  );

  const input = { origin, destination, departAt: timeMode === 'now' ? null : departAt };
  const stale = state.status === 'success' && submittedKey !== null && submittedKey !== requestKey(input);

  // Setelah hasil tiba: fokuskan judul hasil dan gulir ke sana (pembaca layar + layar kecil).
  useEffect(() => {
    if (state.status !== 'success') return;

    const frame = requestAnimationFrame(() => {
      headingRef.current?.focus({ preventScroll: true });
      resultRef.current?.scrollIntoView({
        behavior: prefersReducedMotion() ? 'auto' : 'smooth',
        block: 'start',
      });
    });

    return () => cancelAnimationFrame(frame);
  }, [state]);

  useEffect(() => {
    const holder = pickAbortRef;

    return () => holder.current?.abort();
  }, []);

  const handleStatusChange = useCallback((status: MapStatus) => setMapStatus(status), []);

  function clearFieldError(field: 'origin' | 'destination') {
    setErrors((current) => ({ ...current, [field]: undefined, form: undefined }));
  }

  function handleOrigin(place: PickedPlace | null) {
    setOrigin(place);
    if (place) clearFieldError('origin');
    setPickNotice((n) => (n?.target === 'origin' ? null : n));
  }

  function handleDestination(place: PickedPlace | null) {
    setDestination(place);
    if (place) clearFieldError('destination');
    setPickNotice((n) => (n?.target === 'destination' ? null : n));
  }

  function handleSwap() {
    setOrigin(destination);
    setDestination(origin);
    setPickNotice(null);
    setErrors({});
  }

  function handleTimeMode(mode: TimeMode) {
    setTimeMode(mode);
    setErrors((current) => ({ ...current, departAt: undefined }));

    if (mode === 'custom' && !departAt) {
      const now = wibInputValue();

      setDepartAt(now);
      setMinDepart(now);
    }
  }

  function handleExample(example: RouteExample) {
    const now = wibInputValue();

    setOrigin(example.origin);
    setDestination(example.destination);
    setTimeMode('custom');
    setMinDepart(now);
    setDepartAt(nextWibOccurrence(example.hour));
    setErrors({});
    setPickNotice(null);
    setPickTarget(null);
  }

  function togglePick(target: PickTarget) {
    setPickNotice(null);

    if (pickTarget === target) {
      setPickTarget(null);
      return;
    }

    setPickTarget(target);
    mapSectionRef.current?.scrollIntoView({
      behavior: prefersReducedMotion() ? 'auto' : 'smooth',
      block: 'center',
    });
  }

  async function handlePickPoint(latitude: number, longitude: number) {
    const target = pickTarget;

    if (!target) return;

    pickAbortRef.current?.abort();

    const controller = new AbortController();

    pickAbortRef.current = controller;
    setResolvingPick(true);

    try {
      const result = await placeFromPoint(latitude, longitude, 'map', controller.signal);

      if (result.outOfDiy || !result.place) {
        setPickNotice({ target, text: OUT_OF_DIY_MESSAGE }); // mode pilih tetap aktif: pengguna dapat mengetuk lagi
        return;
      }

      if (target === 'origin') handleOrigin(result.place);
      else handleDestination(result.place);

      setPickNotice(
        result.labelResolved
          ? null
          : { target, text: 'Nama wilayah belum dapat dimuat, tetapi titik yang Anda pilih tetap dipakai.' },
      );
      setPickTarget(null);
    } catch (error) {
      if (!isAbortError(error)) {
        setPickNotice({ target, text: 'Titik belum dapat diproses. Coba ketuk lagi.' });
      }
    } finally {
      if (pickAbortRef.current === controller) setResolvingPick(false);
    }
  }

  const runCheck = useCallback(
    async (current: { origin: PickedPlace; destination: PickedPlace; departAt: string | null }) => {
      const departure = current.departAt === null ? wibInputToIso(wibInputValue()) : wibInputToIso(current.departAt);

      const body: RouteCheckBody = {
        origin: { latitude: current.origin.latitude, longitude: current.origin.longitude },
        destination: { latitude: current.destination.latitude, longitude: current.destination.longitude },
        ...(departure ? { departure_time: departure } : {}),
      };

      setPickTarget(null);
      setSelectedRoute(0);
      setFocusedSegment(null);
      setSubmittedKey(requestKey(current));
      setSubmittedLabels({ origin: current.origin.label, destination: current.destination.label });

      await check(body, { narrative });
    },
    [check, narrative],
  );

  function handleSubmit() {
    const found = validateRouteForm(input);

    setErrors(found);

    if (hasErrors(found) || !origin || !destination) return;

    void runCheck({ origin, destination, departAt: input.departAt });
  }

  function showMap() {
    mapSectionRef.current?.scrollIntoView({
      behavior: prefersReducedMotion() ? 'auto' : 'smooth',
      block: 'start',
    });
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(380px,460px)_minmax(0,1fr)] lg:items-start">
      <div className="order-2 min-w-0 space-y-6 lg:order-1">
        <RouteForm
          origin={origin}
          destination={destination}
          onOriginChange={handleOrigin}
          onDestinationChange={handleDestination}
          onSwap={handleSwap}
          pickTarget={pickTarget}
          onTogglePick={mapUsable ? togglePick : undefined}
          pickNotice={pickNotice}
          timeMode={timeMode}
          onTimeModeChange={handleTimeMode}
          departAt={departAt}
          onDepartAtChange={(value) => {
            setDepartAt(value);
            setErrors((current) => ({ ...current, departAt: undefined }));
          }}
          minDepart={minDepart}
          narrative={narrative}
          onNarrativeChange={setNarrative}
          errors={errors}
          loading={loading}
          onSubmit={handleSubmit}
          onExample={handleExample}
        />

        <div ref={resultRef} className="scroll-mt-24" aria-live="polite">
          {state.status === 'idle' && <RouteIdlePanel />}

          {state.status === 'loading' && <RouteLoadingPanel step={state.step} />}

          {state.status === 'error' && (
            <RouteErrorPanel
              message={state.message}
              kind={state.kind}
              onRetry={handleSubmit}
            />
          )}

          {state.status === 'success' && views && (
            <RouteResultPanel
              ref={headingRef}
              data={state.data}
              views={views}
              selectedIndex={selectedRoute}
              onSelectRoute={(index) => {
                setSelectedRoute(index);
                setFocusedSegment(null);
              }}
              focusedSegment={focusedSegment}
              onFocusSegment={setFocusedSegment}
              stale={stale}
              originLabel={submittedLabels.origin}
              destinationLabel={submittedLabels.destination}
              onShowMap={showMap}
              mapAvailable={mapUsable}
            />
          )}
        </div>
      </div>

      <div
        ref={mapSectionRef}
        className="order-1 scroll-mt-24 lg:sticky lg:top-24 lg:order-2"
      >
        <RouteMap
          className="h-[48vh] min-h-[320px] lg:h-[calc(100dvh-8rem)] lg:min-h-[520px]"
          origin={origin}
          destination={destination}
          views={views}
          selectedIndex={selectedRoute}
          onSelectRoute={(index) => {
            setSelectedRoute(index);
            setFocusedSegment(null);
          }}
          focusedSegment={focusedSegment}
          onFocusSegment={setFocusedSegment}
          pickTarget={pickTarget}
          onPickPoint={handlePickPoint}
          onCancelPick={() => setPickTarget(null)}
          resolvingPick={resolvingPick}
          onStatusChange={handleStatusChange}
        />
      </div>
    </div>
  );
}
