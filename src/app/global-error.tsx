'use client';

/** Cadangan terakhir bila layout akar sendiri gagal; harus membawa <html>/<body> dan gaya inline (CSS global mungkin tak termuat). */
export default function GlobalError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <html lang="id">
      <body
        style={{
          margin: 0,
          minHeight: '100vh',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 16,
          padding: 24,
          textAlign: 'center',
          background: '#060a08',
          color: '#e4e4e7',
          fontFamily: 'system-ui, sans-serif',
        }}
      >
        <h1 style={{ fontSize: 28, margin: 0 }}>Gardu belum dapat dimuat</h1>
        <p style={{ maxWidth: 420, margin: 0, color: '#a1a1aa' }}>Terjadi kesalahan tak terduga. Silakan coba lagi.</p>
        <button
          type="button"
          onClick={reset}
          style={{ border: 0, borderRadius: 999, padding: '10px 24px', background: '#34d399', color: '#022c22', fontWeight: 600, cursor: 'pointer' }}
        >
          Coba lagi
        </button>
      </body>
    </html>
  );
}
