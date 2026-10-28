'use client';

import { useState } from 'react';

import { getSupabase } from '@/lib/supabase/client';

interface Props {
  notice?: string;
  onSignedIn: () => void;
}

/** Pesan aman dari error Supabase Auth: tidak membedakan "email tak ada" dan "kata sandi salah". */
function signInMessage(error: { status?: number; name?: string }): string {
  if (error.name === 'AuthRetryableFetchError' || error.status === 0) {
    return 'Tidak dapat terhubung ke layanan masuk. Periksa koneksi internet Anda lalu coba lagi.';
  }

  if (error.status === 429) return 'Terlalu banyak percobaan. Tunggu sebentar lalu coba lagi.';
  if (error.status && error.status >= 500) return 'Layanan masuk sedang bermasalah. Coba lagi beberapa saat lagi.';

  return 'Email atau kata sandi tidak sesuai.';
}

export default function LoginForm({ notice, onSignedIn }: Props) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();

    if (submitting) return;

    if (!email.trim() || !password) {
      setError('Isi email dan kata sandi.');
      return;
    }

    setSubmitting(true);
    setError(null);

    try {
      const { error: authError } = (await getSupabase()?.auth.signInWithPassword({ email: email.trim(), password })) ?? {
        error: { status: 0 },
      };

      if (authError) {
        setError(signInMessage(authError));
        setSubmitting(false);
        return;
      }

      // Sesi tersimpan oleh Supabase; gerbang memverifikasi hak moderator ke backend.
      onSignedIn();
    } catch {
      setError(signInMessage({ status: 0 }));
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} noValidate>
      <h2 className="font-display text-xl font-bold text-white">Masuk moderator</h2>
      <p className="mt-2 text-sm leading-relaxed text-zinc-500">Khusus tim moderator Gardu.</p>

      {notice && (
        <p className="mt-4 rounded-xl border border-amber-400/20 bg-amber-400/5 px-3 py-2 text-xs text-amber-200" role="status">
          {notice}
        </p>
      )}

      <label htmlFor="mod-email" className="mt-5 block text-xs font-semibold text-zinc-400">
        Email
      </label>
      <input
        id="mod-email"
        type="email"
        autoComplete="username"
        inputMode="email"
        value={email}
        onChange={(event) => setEmail(event.target.value)}
        className="input mt-1.5"
        disabled={submitting}
        aria-invalid={Boolean(error)}
        aria-describedby={error ? 'mod-login-error' : undefined}
      />

      <label htmlFor="mod-password" className="mt-4 block text-xs font-semibold text-zinc-400">
        Kata sandi
      </label>
      <input
        id="mod-password"
        type="password"
        autoComplete="current-password"
        value={password}
        onChange={(event) => setPassword(event.target.value)}
        className="input mt-1.5"
        disabled={submitting}
        aria-invalid={Boolean(error)}
        aria-describedby={error ? 'mod-login-error' : undefined}
      />

      {error && (
        <p id="mod-login-error" role="alert" className="mt-3 text-xs text-red-300">
          {error}
        </p>
      )}

      <button type="submit" disabled={submitting} className="btn-primary mt-6 w-full disabled:cursor-not-allowed disabled:opacity-60">
        {submitting ? 'Memeriksa…' : 'Masuk'}
      </button>
    </form>
  );
}
