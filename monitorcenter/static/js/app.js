function laptopApp(moduleName) {
  return {
    moduleName,
    activeTab: 'today',

    // Search (top bar, always visible)
    searchQ: '',
    searchResults: [],
    searched: false,

    // Per-tab data
    today:  { stats: {}, records: [] },
    week:   { stats: null, by_brand: [], fail_reasons: [], daily: [], records: [], start: null, end: null },
    month:  { stats: null, by_brand: [], fail_reasons: [], daily: [], records: [], start: null, end: null },
    custom: { stats: null, by_brand: [], fail_reasons: [], daily: [], records: [] },

    customFrom: '',
    customTo:   '',
    detailOpen: null,   // single record expand key
    openSections: {},   // brand/day expand keys
    schema: null,
    allTotal: 0,

    async init() {
      const r = await fetch(`/${this.moduleName}/api/schema`);
      this.schema = await r.json();
      await Promise.all([
        this.loadToday(),
        this.loadWeek(),
        this.loadMonth(),
        fetch(`/${this.moduleName}/api/stats/total`).then(r => r.json()).then(d => { this.allTotal = d.total ?? 0; }).catch(() => {}),
      ]);
      setInterval(() => {
        if (this.activeTab === 'today') this.loadToday();
      }, 10000);
    },

    async loadToday() {
      const r = await fetch(`/${this.moduleName}/api/latest`);
      const records = await r.json();
      const total  = records.length;
      const passed = records.filter(r => r.overall_result === 'PASS').length;
      const failed = total - passed;
      this.today = {
        stats: { total, passed, failed, pass_rate: total ? Math.round(passed / total * 100) : 0 },
        records,
      };
    },

    async loadWeek() {
      const r = await fetch(`/${this.moduleName}/api/stats/range?range=week`);
      const d = await r.json();
      this.week = {
        stats:       { total: d.total, passed: d.passed, failed: d.failed, pass_rate: d.pass_rate },
        by_brand:    (d.brands    ?? []).map(([name, count]) => ({ name, count })),
        fail_reasons:(d.fail_reasons ?? []).map(([reason, count]) => ({ reason, count })),
        daily:       d.daily ?? [],
        records:     d.records ?? [],
        start:       d.date_from,
        end:         d.date_to,
      };
    },

    async loadMonth() {
      const r = await fetch(`/${this.moduleName}/api/stats/range?range=month`);
      const d = await r.json();
      this.month = {
        stats:       { total: d.total, passed: d.passed, failed: d.failed, pass_rate: d.pass_rate },
        by_brand:    (d.brands    ?? []).map(([name, count]) => ({ name, count })),
        fail_reasons:(d.fail_reasons ?? []).map(([reason, count]) => ({ reason, count })),
        daily:       d.daily ?? [],
        records:     d.records ?? [],
        start:       d.date_from,
        end:         d.date_to,
      };
    },

    async loadCustom() {
      if (!this.customFrom || !this.customTo) return;
      const url = `/${this.moduleName}/api/stats/range?from=${this.customFrom}&to=${this.customTo}`;
      const d = await (await fetch(url)).json();
      this.custom = {
        stats:       { total: d.total, passed: d.passed, failed: d.failed, pass_rate: d.pass_rate },
        by_brand:    (d.brands    ?? []).map(([name, count]) => ({ name, count })),
        fail_reasons:(d.fail_reasons ?? []).map(([reason, count]) => ({ reason, count })),
        daily:       d.daily ?? [],
        records:     d.records ?? [],
      };
    },

    async runSearch() {
      if (!this.searchQ.trim()) return;
      const r = await fetch(`/${this.moduleName}/api/search?sn=${encodeURIComponent(this.searchQ.trim())}`);
      this.searchResults = await r.json();
      this.searched = true;
    },

    clearSearch() {
      this.searchQ = '';
      this.searchResults = [];
      this.searched = false;
    },

    toggleDetail(key) {
      this.detailOpen = this.detailOpen === key ? null : key;
    },

    toggleSection(key) {
      this.openSections = { ...this.openSections, [key]: !this.openSections[key] };
    },

    isOpen(key) {
      return !!this.openSections[key];
    },

    normalizeBrand(vendor) {
      if (!vendor) return 'Unknown';
      if (vendor.includes('Dell'))                       return 'Dell';
      if (vendor.includes('HP') || vendor.includes('Hewlett')) return 'HP';
      if (vendor.includes('Lenovo'))                     return 'Lenovo';
      if (vendor.includes('Microsoft'))                  return 'Microsoft';
      if (vendor.includes('Apple'))                      return 'Apple';
      return vendor;
    },

    recordsForBrand(tab, brandName) {
      return (this[tab].records ?? []).filter(r => this.normalizeBrand(r.vendor) === brandName);
    },

    recordsForDay(tab, date) {
      return (this[tab].records ?? []).filter(r => (r.timestamp ?? '').slice(0, 10) === date);
    },

    resultClass(result) {
      if (!result) return '';
      if (result === 'PASS') return 'pass';
      if (result === 'FAIL') return 'fail';
      return 'warn';
    },

    fmtRange(start, end) {
      if (!start || !end) return '';
      const fmt = d => { const p = d.split('-'); return p[1] + '/' + p[2]; };
      return fmt(start) + ' – ' + fmt(end);
    },

    renderDetails(record) {
      if (!this.schema) return '';
      return renderPayload(this.schema, record);
    },
  };
}
