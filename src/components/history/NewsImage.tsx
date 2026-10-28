'use client';

import { useState } from 'react';

/**
 * Gambar sampul berita dari CDN media sumber (domain berbeda-beda, jadi <img> biasa, bukan next/image).
 * Komponen klien karena menangani kegagalan muat: bila gambar tidak bisa dimuat, kartu tetap tampil tanpa gambar.
 */
export default function NewsImage({ src, alt }: { src: string; alt: string }) {
  const [failed, setFailed] = useState(false);

  if (failed) return null;

  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={src}
      alt={alt}
      loading="lazy"
      referrerPolicy="no-referrer"
      className="h-full w-full object-cover transition duration-500 group-hover:scale-[1.04]"
      onError={() => setFailed(true)}
    />
  );
}
