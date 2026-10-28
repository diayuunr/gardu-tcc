import type { Metadata, Viewport } from 'next';
import { Plus_Jakarta_Sans } from 'next/font/google';
import './globals.css';
import Navbar from '@/components/Navbar';
import Footer from '@/components/Footer';
import PageLoader from '@/components/Loader';

export const metadata: Metadata = {
  title: {
    default: 'Gardu - Peta Kerawanan & Rute Aman Yogyakarta',
    template: '%s | Gardu',
  },
  description:
    'Sistem Kesadaran Komunitas dan Rute Aman Warga terhadap Kejahatan Jalanan (Klitih) di Yogyakarta.',
  icons: { icon: '/gardu-icon.svg', },
  openGraph: {
    title: 'Gardu - Peta Kerawanan & Rute Aman Yogyakarta',
    description: 'Peta kerawanan, cek rute, dan lapor kejadian jalanan di Yogyakarta berdasarkan data tercatat.',
    siteName: 'Gardu',
    locale: 'id_ID',
    type: 'website',
  },
};

export const viewport: Viewport = {
  themeColor: '#060a08',
};

const jakarta = Plus_Jakarta_Sans({
  subsets: ['latin'],
  variable: '--font-jakarta',
});

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="id">
      <body className={`${jakarta.className} min-h-screen`}>
        <PageLoader />
        <Navbar />
        <main className="relative z-[2]">{children}</main>
        <Footer />
      </body>
    </html>
  );
}