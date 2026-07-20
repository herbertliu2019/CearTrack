# Fix: By Brand / Fail Reasons Side-by-Side Equal Height + Tab Rename

## Part 1: Tab Rename

In `modules/laptop/templates/module.html`, update the three tab buttons
display labels and order:

```html
<button class="tab-btn" :class="{active: activeTab==='latest'}"
        @click="activeTab='latest'">Today</button>
<button class="tab-btn" :class="{active: activeTab==='stats'}"
        @click="activeTab='stats'; loadStatsRange()">Stats</button>
<button class="tab-btn" :class="{active: activeTab==='search'}"
        @click="activeTab='search'">Search</button>
```

Order: Today · Stats · Search
`activeTab` internal values (latest/stats/search) do NOT change.

---

## Part 2: By Brand and Common Fail Reasons Side-by-Side Equal Height

### Problem
Two cards are stacked vertically. Must be side-by-side with equal height.

### Fix in `modules/laptop/templates/module.html`

Find the container div wrapping both cards. Replace its style:

```html
<div style="display:flex; flex-direction:row; gap:16px; margin-bottom:20px; align-items:stretch;" x-show="statsData">
```

Each child card div must have:
```html
<div class="detail-panel" style="flex:1; min-width:0;">
```

Key CSS:
- `align-items:stretch` — both cards stretch to the same height
- `flex:1` — equal width
- `min-width:0` — prevents overflow

## Verification
Stats tab → By Brand LEFT, Common Fail Reasons RIGHT,
same height, same top alignment, content starts from top of each card.

## Constraints
- Only modify wrapper div style, card div styles, and tab button labels
- Do not change activeTab values, API calls, or any other logic
