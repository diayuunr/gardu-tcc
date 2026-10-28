/**
 * Berita pilihan (tautan ke sumber asli). Judul dan ringkasan di bawah adalah RINGKASAN NETRAL tim Gardu, sengaja tanpa
 * ciri korban atau terduga pelaku (usia, jenis kelamin, kondisi luka, jumlah orang diamankan); rincian ada di sumber.
 * Gambar sampul adalah foto ilustrasi/arsip dari media sumber dan bukan foto kejadian yang diberitakan; setiap kartu
 * menampilkan catatan itu (`imageNote`). Bila gambar gagal dimuat, kartu tetap tampil tanpa gambar.
 */

export interface NewsItem {
  title: string;
  date: string;
  source: string;
  category: string;
  excerpt: string;
  url: string;
  image: string;
  imageAlt: string;
  imageNote: string;
}

export const NEWS_ITEMS: readonly NewsItem[] = [
  {
    title: 'Polisi menyelidiki dugaan kejahatan jalanan di Pleret, Bantul',
    date: '21 Oktober 2026',
    source: 'detikJogja',
    category: 'Penanganan kasus',
    excerpt:
      'Petugas mendatangi lokasi dan meminta keterangan saksi untuk mendalami kejadian yang dilaporkan di Pleret, Bantul.',
    url: 'https://www.detik.com/jogja/berita/d-8718000/viral-korban-klitih-di-pleret-bantul-terluka-hingga-dioperasi-polisi-selidiki',
    image:
      'https://awsimages.detik.net.id/community/media/visual/2026/02/10/viral-di-bantul-1770705745676_169.jpeg?q=90&w=700',
    imageAlt: 'Ilustrasi penanganan kejadian di wilayah Bantul',
    imageNote: 'Foto ilustrasi/arsip',
  },
  {
    title: 'JPW mendorong pengawasan malam hari diperketat di Bantul',
    date: '19 Oktober 2026',
    source: 'Disway Jogja',
    category: 'Pencegahan',
    excerpt:
      'Jogja Police Watch menyoroti pentingnya evaluasi pencegahan: pengawasan malam hingga dini hari, pendekatan keluarga, dan pelibatan masyarakat.',
    url: 'https://jogja.disway.id/daerah/read/702339/klitih-belum-hilang-jpw-desak-polisi-perketat-pengawasan-malam-di-bantul',
    image: 'https://assets.pikiran-rakyat.com/crop/382x127%3A1242x660/720x0/webp/photo/2025/07/26/3351686213.jpg',
    imageAlt: 'Rekaman CCTV terkait insiden kejahatan jalanan',
    imageNote: 'Foto ilustrasi/arsip',
  },
  {
    title: 'Polisi menangani insiden di Jalan Samas, Sanden, Bantul',
    date: '5 Oktober 2026',
    source: 'detikJogja',
    category: 'Proses hukum',
    excerpt:
      'Polisi memeriksa pihak-pihak terkait dan meminta masyarakat tidak terburu-buru menyimpulkan sebelum penyelidikan selesai.',
    url: 'https://www.detik.com/jogja/berita/d-8692323/belasan-remaja-diamankan-polisi-usai-dihajar-massa-di-bantul',
    image:
      'https://cloud.jpnn.com/photo/arsip/normal/2021/11/30/remaja-diduga-klitih-diamankan-polres-bantul-pada-senin-2911-wc7y.jpg',
    imageAlt: 'Dokumentasi arsip penanganan kasus kejahatan jalanan',
    imageNote: 'Foto arsip, bukan foto kejadian ini',
  },
];
