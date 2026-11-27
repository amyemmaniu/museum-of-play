// Filters and searches a grid of cards on the page.
//
// Each card carries data attributes (set in the page):
//   data-title, data-keywords      text the search box looks through
//   data-category                  one value, e.g. "Exhibit"
//   data-age-groups                values joined with "|", e.g. "18 – 24|25+"
//   data-start, data-end, data-permanent   dates (YYYY-MM-DD) used for the Time filter
//
// Rules: inside one filter, no boxes checked means "don't filter"; checked boxes match ANY of them.
// Different filters (and the search box) must ALL match.

type Group = { label: string; values: (card: HTMLElement) => string[] };

// "Current", "Upcoming" or "Past" for a card, compared with today (UTC, like the dates themselves)
function timeStatus(card: HTMLElement): string {
	if (card.dataset.permanent === 'true') return 'Current';
	const today = new Date().toISOString().slice(0, 10);
	const start = card.dataset.start ?? '';
	const end = card.dataset.end || start; // a single-day item ends the day it starts
	if (today < start) return 'Upcoming';
	if (today > end) return 'Past';
	return 'Current';
}

// The filter dropdown's label decides which card data it looks at
const groups: Group[] = [
	{ label: 'Category', values: (card) => [card.dataset.category ?? ''] },
	{ label: 'Type', values: (card) => [card.dataset.category ?? ''] },
	{ label: 'Age Group', values: (card) => (card.dataset.ageGroups ?? '').split('|') },
	{ label: 'Time', values: (card) => [timeStatus(card)] },
];

export function setupCardFilter(cardsSelector: string, searchSelector: string) {
	const container = document.querySelector<HTMLElement>(cardsSelector);
	const search = document.querySelector<HTMLInputElement>(searchSelector);
	if (!container || !search) return;

	const cards = Array.from(container.children) as HTMLElement[];
	const noResults = document.querySelector<HTMLElement>('.no-results');

	// Each dropdown on the page, paired with the card data it filters on
	const filters = Array.from(document.querySelectorAll<HTMLElement>('.filter')).flatMap((filter) => {
		const label = filter.querySelector('.filter-button')?.textContent?.trim();
		const group = groups.find((g) => g.label === label);
		return group ? [{ filter, group }] : [];
	});

	function apply() {
		const query = search!.value.trim().toLowerCase();

		// For each dropdown: the labels of the checked boxes
		const checkedByFilter = filters.map(({ filter, group }) => ({
			group,
			checked: Array.from(filter.querySelectorAll<HTMLInputElement>('input[type="checkbox"]:checked'))
				.map((box) => box.closest('label')?.textContent?.trim() ?? ''),
		}));

		let visible = 0;
		for (const card of cards) {
			const haystack = `${card.dataset.title ?? ''} ${card.dataset.keywords ?? ''}`.toLowerCase();
			const matchesSearch = haystack.includes(query);
			const matchesFilters = checkedByFilter.every(({ group, checked }) =>
				checked.length === 0 || group.values(card).some((value) => checked.includes(value)),
			);
			card.hidden = !(matchesSearch && matchesFilters);
			if (!card.hidden) visible++;
		}
		if (noResults) noResults.hidden = visible > 0;
	}

	search.addEventListener('input', apply);
	filters.forEach(({ filter }) => filter.addEventListener('change', apply));
	apply();
}
