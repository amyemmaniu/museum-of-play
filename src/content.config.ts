import { defineCollection } from 'astro:content';
import { glob } from 'astro/loaders';
import { z } from 'astro/zod';

// Each blog post is a Markdown file in src/content/blog/
const blog = defineCollection({
	loader: glob({ pattern: '**/*.md', base: './src/content/blog' }),
	schema: ({ image }) =>
		z.object({
			title: z.string(),
			date: z.coerce.date(),
			category: z.string().optional(),
			// At least one image is required; the first one is the BlogPostCard image
			images: z.array(z.object({ src: image(), alt: z.string() })).min(1),
		}),
});

export const collections = { blog };
