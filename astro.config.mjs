import { defineConfig } from 'astro/config';

// GH Pages project-site deploy: set site/base when the repo goes public.
export default defineConfig({
  build: { format: 'directory' },
  trailingSlash: 'ignore',
});
