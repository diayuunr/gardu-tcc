'use client';

import { useEffect, useState } from 'react';
import { LogOut, RefreshCw } from 'react-feather';

import LoginForm from '@/components/admin/LoginForm';
import ModerationQueue from '@/components/admin/ModerationQueue';
import { ApiError, errorMessage, isAbortError } from '@/lib/api';
import { fetchModerator } from '@/lib/moderation-api';
import { SUPABASE_CONFIGURED, getSupabase } from '@/lib/supabase/client';

type Gate =
  | { kind: 'unconfigured' }
  | { kind: 'checking' }
  | { kind: 'signed_out'; notice?: string }
  | { kind: 'forbidden' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; name: string };

function Card({ children }: { children: React.ReactNode }) {
  return <div className="glass-card mx-auto max-w-md p-6 sm:p-8">{children}</div>;
}

/** Gerbang panel: sesi Supabase -> /moderation/me (token + hak akses) -> antrean. */
export default function ModerationPanel() {
  const [gate, setGate] = useState<Gate>(SUPABASE_CONFIGURED ? { kind: 'checking' } : { kind: 'unconfigured' });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!SUPABASE_CONFIGURED) return;

    const controller = new AbortController();

    async function check() {
      const { data } = (await getSupabase()?.auth.getSession()) ?? { data: { session: null } };

      if (controller.signal.aborted) return;

      if (!data.session) {
        setGate({ kind: 'signed_out' });
        return;
      }

      try {
        const me = await fetchModerator(controller.signal);

        setGate({ kind: 'ready', name: me.display_name });
      } catch (error) {
        if (isAbortError(error)) return;

        if (error instanceof ApiError && error.kind === 'unauthorized') {
          await getSupabase()?.auth.signOut();
          setGate({ kind: 'signed_out', notice: 'Sesi Anda sudah berakhir. Silakan masuk kembali.' });
        } else if (error instanceof ApiError && error.kind === 'forbidden') {
          setGate({ kind: 'forbidden' });
        } else {
          setGate({ kind: 'error', message: errorMessage(error) });
        }
      }
    }

    void check();

    return () => controller.abort();
  }, [attempt]);

  function recheck() {
    setGate({ kind: 'checking' });
    setAttempt((value) => value + 1);
  }

  async function signOut(notice?: string) {
    await getSupabase()?.auth.signOut();
    setGate({ kind: 'signed_out', notice });
  }

  if (gate.kind === 'unconfigured') {
    return (
      <Card>
        <h2 className="font-display text-xl font-bold text-white">Panel belum dikonfigurasi</h2>
        <p className="mt-3 text-sm leading-relaxed text-zinc-400" role="alert">
          Layanan masuk moderator belum diatur pada aplikasi ini. Hubungi pengelola sistem.
        </p>
      </Card>
    );
  }

  if (gate.kind === 'checking') {
    return (
      <Card>
        <div className="space-y-3" role="status" aria-label="Memeriksa sesi">
          <div className="h-6 w-40 animate-pulse rounded bg-zinc-800 motion-reduce:animate-none" />
          <div className="h-10 animate-pulse rounded-2xl bg-zinc-800 motion-reduce:animate-none" />
          <div className="h-10 animate-pulse rounded-2xl bg-zinc-800 motion-reduce:animate-none" />
        </div>
      </Card>
    );
  }

  if (gate.kind === 'signed_out') {
    return (
      <Card>
        <LoginForm notice={gate.notice} onSignedIn={recheck} />
      </Card>
    );
  }

  if (gate.kind === 'forbidden') {
    return (
      <Card>
        <h2 className="font-display text-xl font-bold text-white">Akses ditolak</h2>
        <p className="mt-3 text-sm leading-relaxed text-zinc-400" role="alert">
          Akun ini berhasil masuk tetapi belum terdaftar sebagai moderator. Minta pengelola sistem menambahkan akun Anda,
          atau masuk dengan akun lain.
        </p>
        <button type="button" onClick={() => void signOut()} className="btn-ghost mt-5 !px-5 !py-2">
          <LogOut size={14} aria-hidden="true" />
          Keluar
        </button>
      </Card>
    );
  }

  if (gate.kind === 'error') {
    return (
      <Card>
        <h2 className="font-display text-xl font-bold text-white">Belum dapat memeriksa akses</h2>
        <p className="mt-3 text-sm leading-relaxed text-zinc-400" role="alert">
          {gate.message}
        </p>
        <div className="mt-5 flex flex-wrap gap-3">
          <button type="button" onClick={recheck} className="btn-primary !px-5 !py-2">
            <RefreshCw size={14} aria-hidden="true" />
            Coba lagi
          </button>
          <button type="button" onClick={() => void signOut()} className="btn-ghost !px-5 !py-2">
            Keluar
          </button>
        </div>
      </Card>
    );
  }

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-line bg-ink/50 px-4 py-3">
        <p className="text-sm text-zinc-400">
          Masuk sebagai <strong className="text-white">{gate.name}</strong>
        </p>
        <button type="button" onClick={() => void signOut()} className="btn-ghost !px-4 !py-1.5 text-xs">
          <LogOut size={13} aria-hidden="true" />
          Keluar
        </button>
      </div>

      <ModerationQueue
        onSessionEnd={(kind) =>
          kind === 'forbidden'
            ? setGate({ kind: 'forbidden' })
            : void signOut('Sesi Anda sudah berakhir. Silakan masuk kembali.')
        }
      />
    </div>
  );
}
