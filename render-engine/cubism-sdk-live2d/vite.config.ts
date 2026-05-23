import { defineConfig } from 'vite';
import path from 'path';

const frameworkRoot = path.resolve(
  __dirname,
  '../../../CubismWebSamples/Framework/src'
);

export default defineConfig({
  root: '.',
  base: './',
  publicDir: 'public',
  resolve: {
    extensions: ['.ts', '.js'],
    alias: [
      {
        find: '@framework',
        replacement: frameworkRoot,
      },
    ],
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    assetsDir: 'assets',
    rollupOptions: {
      input: path.resolve(__dirname, 'render.src.html'),
      output: {
        entryFileNames: 'assets/avatar.js',
        chunkFileNames: 'assets/[name].js',
        assetFileNames: 'assets/[name][extname]',
      },
    },
  },
});
