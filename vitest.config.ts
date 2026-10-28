import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';

// Hanya fungsi murni (tanpa DOM): lingkungan node. Uji dijalankan juga dengan TZ lain untuk memastikan logika WIB tidak bergantung mesin.
export default defineConfig({
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  test: { environment: 'node', include: ['src/**/*.test.ts'] },
});
