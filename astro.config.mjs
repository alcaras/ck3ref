import { defineConfig } from 'astro/config';

// Deployed as a GitHub Pages project site.
export default defineConfig({
  site: 'https://alcaras.github.io',
  base: '/ck3ref/',
  build: { format: 'directory' },
  trailingSlash: 'ignore',
});
