// @ts-check
import { defineConfig } from 'astro/config';
import { fileURLToPath } from 'node:url';

// Absolute path to the shared SCSS variables, with forward slashes so Sass accepts it on Windows
const variablesPath = fileURLToPath(new URL('./src/styles/variables.scss', import.meta.url)).replace(/\\/g, '/');

// https://astro.build/config
export default defineConfig({
	site: 'https://museum-of-play.workers.dev',
	vite: {
		css: {
			preprocessorOptions: {
				scss: {
					// Makes every variable in variables.scss available in every SCSS file and <style lang="scss"> block
					additionalData: `@use "${variablesPath}" as *;\n`,
				},
			},
		},
	},
});
