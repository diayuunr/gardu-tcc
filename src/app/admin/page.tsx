'use client';

import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import Reveal from '@/components/Reveal';
import { supabase, isMockMode } from '@/lib/supabase';
import { Report, ReportStatus } from '@/lib/types';

const STATUS_STYLE: Record<ReportStatus, string> = {
  menunggu_verifikasi:
    'border-amber-400/30 bg-amber-400/10 text-amber-300',
  terverifikasi:
    'border-emerald-400/30 bg-emerald-400/10 text-emerald-300',
  duplikat:
    'border-sky-400/30 bg-sky-400/10 text-sky-300',
  hoaks:
    'border-red-400/30 bg-red-400/10 text-red-300',
};

const MOCK_REPORTS: Report[] = [
  {
    id: 'demo-1',
    description:
      'Dua pemuda menodong pengendara motor di dekat Tugu jam setengah dua malam tadi. Korban selamat, motornya dibawa kabur.',
    location_text: 'Malioboro & Tugu',
    occurred_at: new Date(Date.now() - 86400000).toISOString(),
    incident_type: 'penodongan',
    status: 'terverifikasi',
    ai_summary:
      'AI mengidentifikasi indikasi penodongan. Klaster konsisten dengan 2 laporan independen.',
  },
  {
    id: 'demo-2',
    description:
      'http://link-janggal Laporan tidak jelas tanpa detail lokasi.',
    location_text: 'Ring Road Utara (Mlati)',
    occurred_at: new Date(Date.now() - 43200000).toISOString(),
    status: 'menunggu_verifikasi',
    ai_summary:
      'Deskripsi terlalu pendek — butuh tinjauan moderator.',
    flagged_reason:
      'Mengandung tautan — potensi tidak konsisten.',
  },
];

export default function AdminPage() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

  const [session, setSession] = useState(isMockMode);

  const [loginError, setLoginError] = useState('');

  const [reports, setReports] = useState<Report[]>(
    isMockMode ? MOCK_REPORTS : []
  );

  const [filter, setFilter] = useState<ReportStatus | 'semua'>('semua');

  // Mode demo: langsung tampilkan data mock tanpa login
  useEffect(() => {
    if (isMockMode) return;

    if (!supabase) return;

    supabase.auth
      .getSession()
      .then(({ data }) => setSession(!!data.session));

    const { data: sub } = supabase.auth.onAuthStateChange((_e, s) =>
      setSession(!!s)
    );

    return () => sub.subscription.unsubscribe();
  }, []);

  useEffect(() => {
    if (!session || isMockMode || !supabase) return;

    supabase
      .from('reports')
      .select('*')
      .order('created_at', { ascending: false })
      .then(({ data }) => setReports((data as Report[]) ?? []));
  }, [session]);

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault();

    if (!supabase) return;

    const { error } = await supabase.auth.signInWithPassword({
      email,
      password,
    });

    if (error) {
      setLoginError(
        'Login gagal. Pastikan akun sudah di-invite di Supabase Auth.'
      );
    }
  }

  async function updateStatus(id: string, status: ReportStatus) {
    setReports((prev) =>
      prev.map((r) =>
        r.id === id
          ? { ...r, status }
          : r
      )
    );

    if (isMockMode || !supabase) return;

    await supabase
      .from('reports')
      .update({ status })
      .eq('id', id);
  }

  const filtered =
    filter === 'semua'
      ? reports
      : reports.filter((r) => r.status === filter);

  if (!session) {
    return (
      <div className="container-x flex min-h-screen items-center justify-center pb-24 pt-32">
        <Reveal className="w-full max-w-sm">
          <form
            onSubmit={handleLogin}
            className="glass-card space-y-5 p-8"
          >
            <div className="text-center">
              <h1 className="font-display text-2xl font-bold text-white">
                Panel Moderasi
              </h1>

              <p className="mt-2 text-sm text-zinc-500">
                Khusus anggota tim (Supabase Auth).
              </p>
            </div>

            <input
              type="email"
              required
              placeholder="Email tim"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="input"
            />

            <input
              type="password"
              required
              placeholder="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="input"
            />

            {loginError && (
              <p className="text-sm text-red-300">
                {loginError}
              </p>
            )}

            <button
              type="submit"
              className="btn-primary w-full"
            >
              Masuk
            </button>
          </form>
        </Reveal>
      </div>
    );
  }

  return (
    <div className="container-x min-h-screen pb-24 pt-32">
      <Reveal>
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.3em] text-emerald-400">
              Internal
            </p>

            <h1 className="mt-3 font-display text-4xl font-bold text-white">
              Panel Moderasi
            </h1>

            <p className="mt-2 text-zinc-500">
              Tinjau laporan yang ditandai AI, lalu putuskan statusnya
              secara manual (REQ-F-061).
            </p>
          </div>

          {!isMockMode && supabase && (
            <button
              onClick={() => supabase!.auth.signOut()}
              className="btn-ghost"
            >
              Keluar
            </button>
          )}
        </div>
      </Reveal>

      <Reveal delay={0.1}>
        <div className="mt-8 flex flex-wrap gap-2">
          {(
            [
              'semua',
              'menunggu_verifikasi',
              'terverifikasi',
              'duplikat',
              'hoaks',
            ] as const
          ).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`rounded-full px-4 py-2 text-xs font-semibold transition ${
                filter === f
                  ? 'bg-emerald-400 text-emerald-950'
                  : 'border border-line text-zinc-400 hover:text-white'
              }`}
            >
              {f === 'semua'
                ? 'Semua'
                : f.replace('_', ' ')}
            </button>
          ))}
        </div>
      </Reveal>

      <div className="mt-6 space-y-4">
        {filtered.length === 0 && (
          <div className="glass-card p-10 text-center text-sm text-zinc-500">
            Tidak ada laporan pada filter ini.
          </div>
        )}

        {filtered.map((r, i) => (
          <Reveal key={r.id} delay={i * 0.05}>
            <motion.div
              layout
              className="glass-card p-6"
            >
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="max-w-2xl">
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={`rounded-full border px-3 py-1 text-[11px] font-semibold ${STATUS_STYLE[r.status]}`}
                    >
                      {r.status.replace('_', ' ')}
                    </span>

                    {r.incident_type && (
                      <span className="rounded-full border border-line px-3 py-1 text-[11px] text-zinc-400">
                        {r.incident_type}
                      </span>
                    )}
                  </div>

                  <p className="mt-3 text-sm leading-relaxed text-zinc-200">
                    {r.description}
                  </p>

                  <p className="mt-2 text-xs text-zinc-500">
                    {r.location_text} -{' '}
                    {new Date(r.occurred_at).toLocaleString(
                      'id-ID'
                    )}
                  </p>

                  {(r.ai_summary || r.flagged_reason) && (
                    <div className="mt-3 rounded-2xl border border-line bg-ink/50 p-3 text-xs leading-relaxed text-zinc-500">
                      {r.ai_summary && (
                        <p>
                          <span className="text-emerald-400">
                            AI:
                          </span>{' '}
                          {r.ai_summary}
                        </p>
                      )}

                      {r.flagged_reason && (
                        <p className="mt-1">
                          <span className="text-red-300">
                            Flag:
                          </span>{' '}
                          {r.flagged_reason}
                        </p>
                      )}
                    </div>
                  )}
                </div>

                <div className="flex shrink-0 flex-col gap-2">
                  <button
                    onClick={() =>
                      updateStatus(
                        r.id,
                        'terverifikasi'
                      )
                    }
                    className="rounded-xl border border-emerald-400/30 bg-emerald-400/10 px-4 py-2 text-xs font-semibold text-emerald-300 transition hover:bg-emerald-400/20"
                  >
                    Setuju (verifikasi)
                  </button>

                  <button
                    onClick={() =>
                      updateStatus(
                        r.id,
                        'duplikat'
                      )
                    }
                    className="rounded-xl border border-sky-400/30 bg-sky-400/10 px-4 py-2 text-xs font-semibold text-sky-300 transition hover:bg-sky-400/20"
                  >
                    Tandai duplikat
                  </button>

                  <button
                    onClick={() =>
                      updateStatus(
                        r.id,
                        'hoaks'
                      )
                    }
                    className="rounded-xl border border-red-400/30 bg-red-400/10 px-4 py-2 text-xs font-semibold text-red-300 transition hover:bg-red-400/20"
                  >
                    Tandai hoaks
                  </button>
                </div>
              </div>
            </motion.div>
          </Reveal>
        ))}
      </div>
    </div>
  );
}