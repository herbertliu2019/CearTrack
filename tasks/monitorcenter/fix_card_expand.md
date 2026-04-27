# Fix: Latest Tab Card Expand Behavior

## Problems

### Problem 1 — All cards expand/collapse together
`toggleExpand()` uses `r.sn` as the key. If multiple records share the
same SN, they all toggle together. Even with unique SNs, `expandedSn`
is a single value so only one card can be open at a time — clicking
a second card closes the first.

**Required behavior:**
- Each card expands/collapses independently
- Multiple cards can be open simultaneously
- Clicking an open card closes only that card
- Other cards are unaffected

### Problem 2 — Click target too small
`@click="toggleExpand(...)"` is only on `card-header` div.
The cursor shows a pointer hand over the whole card (from CSS
`cursor: pointer` on `.result-card`) but clicking the body does nothing.

**Required behavior:**
- Clicking anywhere on the card toggles that card's expand state

---

## Fix

### 1. Change expanded state from single value to a Set

In `static/js/app.js`, in the `dashboardApp()` function:

**Change:**
```javascript
expandedSn: null,
```

**To:**
```javascript
expandedKeys: new Set(),
```

### 2. Update toggleExpand to use unique key (sn + timestamp)

**Change:**
```javascript
toggleExpand(sn) {
    this.expandedSn = this.expandedSn === sn ? null : sn;
},
```

**To:**
```javascript
toggleExpand(key) {
    if (this.expandedKeys.has(key)) {
        this.expandedKeys.delete(key);
    } else {
        this.expandedKeys.add(key);
    }
    // Alpine needs reassignment to detect Set mutation
    this.expandedKeys = new Set(this.expandedKeys);
},

isExpanded(key) {
    return this.expandedKeys.has(key);
},
```

### 3. Update template in module.html

The card key must be unique — use `r.sn + '_' + r.timestamp`.

**Change the card template:**

```html
<!-- OLD -->
<div :class="'result-card ' + r.overall_result.toLowerCase()">
  <div class="card-header" @click="toggleExpand(r.sn)">
    ...
  </div>
  ...
  <template x-if="expandedSn === r.sn">
```

**To:**

```html
<!-- NEW -->
<div :class="'result-card ' + r.overall_result.toLowerCase()"
     @click="toggleExpand(r.sn + '_' + r.timestamp)"
     style="cursor: pointer;">
  <div class="card-header">
    ...
  </div>
  ...
  <template x-if="isExpanded(r.sn + '_' + r.timestamp)">
```

Key changes:
- `@click` moves from `card-header` to the root `div` of the card
- Remove `@click` from `card-header` entirely
- Use `r.sn + '_' + r.timestamp` as unique key
- Use `isExpanded(key)` instead of `expandedSn === r.sn`

---

## Verification

1. POST two test JSONs with different SNs
2. Click card 1 body anywhere → expands, card 2 stays closed
3. Click card 2 body anywhere → expands, card 1 stays open
4. Click card 1 again → card 1 closes, card 2 stays open
5. If same SN appears twice (re-tested machine), each record expands independently

## Constraints
- Only modify `static/js/app.js` and `modules/laptop/templates/module.html`
- Do not change API endpoints or storage logic
- Run `python -m py_compile app.py` after changes (no Python changes expected)
