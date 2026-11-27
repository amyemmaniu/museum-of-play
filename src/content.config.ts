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
			author: z.string(), // shown as "By: <author>" under the date, e.g. "Jane Doe, Contributor"
			category: z.string().optional(),
			// At least one image is required; the first one is the BlogPostCard image
			images: z.array(z.object({ src: image(), alt: z.string() })).min(1),
		}),
});

// Each exhibit or event on view is a Markdown file in src/content/on-view/
const onView = defineCollection({
	loader: glob({ pattern: '**/*.md', base: './src/content/on-view' }),
	schema: ({ image }) =>
		z.object({
			title: z.string(),
			date: z.coerce.date(), // start date (used to order the page, newest first)
			endDate: z.coerce.date().optional(), // leave out for a single day
			permanent: z.boolean().default(false), // permanent installations show "Permanent Installation"
			category: z.enum(['Exhibit', 'Event']).default('Exhibit'), // shown as the card's badge
			// At least one image is required; the first one is the ViewCard image
			images: z.array(z.object({ src: image(), alt: z.string() })).min(1),
			// Optional: the image shown at the top of this item's own page.
			// Leave it out and the page shows the images above instead.
			banner: z.object({ src: image(), alt: z.string() }).optional(),
		}),
});

export const collections = { blog, 'on-view': onView };
