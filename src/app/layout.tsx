import type { Metadata } from 'next';
import { Plus_Jakarta_Sans } from 'next/font/google';
import './globals.css';
import Navbar from '@/components/Navbar';
import Footer from '@/components/Footer';
import PageLoader from '@/components/Loader';

export const metadata: Metadata = {
  title: 'Gardu - Peta Kerawanan & Rute Aman Yogyakarta',
  description:
    'Sistem Kesadaran Komunitas dan Rute Aman Warga terhadap Kejahatan Jalanan (Klitih) di Yogyakarta.',
  icons: { icon: '/gardu-icon.svg', },
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