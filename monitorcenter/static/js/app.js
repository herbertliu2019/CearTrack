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
    groupBy: 'date',    // 'date' | 'operator'  (week/month/custom)
    todayGroupBy: 'all', // 'all'  | 'operator'  (today tab)
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
      const warned = records.filter(r => r.overall_result === 'WARN').length;
      const failed = records.filter(r => r.overall_result === 'FAIL').length;
      this.today = {
        stats: { total, passed, warned, failed, pass_rate: total ? Math.round(passed / total * 100) : 0 },
        records,
      };
    },

    async loadWeek() {
      const r = await fetch(`/${this.moduleName}/api/stats/range?range=week`);
      const d = await r.json();
      this.week = {
        stats:       { total: d.total, passed: d.passed, warned: d.warned ?? 0, failed: d.failed, pass_rate: d.pass_rate },
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
        stats:       { total: d.total, passed: d.passed, warned: d.warned ?? 0, failed: d.failed, pass_rate: d.pass_rate },
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
        stats:       { total: d.total, passed: d.passed, warned: d.warned ?? 0, failed: d.failed, pass_rate: d.pass_rate },
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

    // Default-OPEN variant for the By-Operator breakdown groups.
    isOpOpen(key) {
      return this.openSections[key] !== false;
    },
    toggleOp(key) {
      const open = this.openSections[key] !== false;   // currently open?
      this.openSections = { ...this.openSections, [key]: !open };
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

    // Today tab: group the day's records by operator (no date sub-level).
    todayByOperator() {
      const records = (this.today.records ?? []);
      const opMap = {};
      for (const rec of records) {
        const op = rec.payload?.test_info?.operator_id || '—';
        if (!opMap[op]) opMap[op] = [];
        opMap[op].push(rec);
      }
      return Object.entries(opMap)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([op, recs]) => ({
          op,
          total:  recs.length,
          passed: recs.filter(r => r.overall_result === 'PASS').length,
          warned: recs.filter(r => r.overall_result === 'WARN').length,
          failed: recs.filter(r => r.overall_result === 'FAIL').length,
          records: recs,
        }));
    },

    groupByOperator(tab) {
      const records = (this[tab].records ?? []);
      const opMap = {};
      for (const rec of records) {
        const op = rec.payload?.test_info?.operator_id || '—';
        if (!opMap[op]) opMap[op] = [];
        opMap[op].push(rec);
      }
      return Object.entries(opMap)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([op, recs]) => {
          const total  = recs.length;
          const passed = recs.filter(r => r.overall_result === 'PASS').length;
          const warned = recs.filter(r => r.overall_result === 'WARN').length;
          const failed = recs.filter(r => r.overall_result === 'FAIL').length;
          const dateMap = {};
          for (const rec of recs) {
            const d = (rec.timestamp ?? '').slice(0, 10);
            if (!dateMap[d]) dateMap[d] = [];
            dateMap[d].push(rec);
          }
          const dates = Object.entries(dateMap)
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([date, dr]) => ({
              date,
              total:  dr.length,
              passed: dr.filter(r => r.overall_result === 'PASS').length,
              warned: dr.filter(r => r.overall_result === 'WARN').length,
              failed: dr.filter(r => r.overall_result === 'FAIL').length,
              records: dr,
            }));
          return { op, total, passed, warned, failed, dates };
        });
    },

    resultClass(result) {
      if (!result) return '';
      if (result === 'PASS') return 'pass';
      if (result === 'FAIL') return 'fail';
      return 'warn';
    },

    fmtRange(start, end) {
      if (!start || !end) return '';
      const [sy, sm, sd] = start.split('-');
      const [ey, em, ed] = end.split('-');
      if (sy === ey) {
        return `${sm}/${sd} – ${em}/${ed}, ${sy}`;
      }
      return `${sm}/${sd}/${sy} – ${em}/${ed}/${ey}`;
    },

    // ── Daily Volume chart helpers ────────────────────────────────────
    jumpToDay(date, tab) {
      // Open the day section in the breakdown table, then scroll to it
      const key = tab + '_day_' + date;
      this.openSections = { ...this.openSections, [key]: true };
      this.$nextTick(() => {
        const el = document.getElementById('db-row-' + tab + '-' + date);
        if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      });
    },

    paddedDailyData(tab) {
      const data = this[tab];
      const daily = data?.daily ?? [];
      const map = {};
      daily.forEach(d => { map[d.date] = d; });
      const empty = (date) => ({ date, total: 0, passed: 0, warned: 0, failed: 0 });
      // Local YYYY-MM-DD (avoid UTC drift from toISOString in PST/PDT)
      const ymd = (dt) => `${dt.getFullYear()}-${String(dt.getMonth()+1).padStart(2,'0')}-${String(dt.getDate()).padStart(2,'0')}`;
      if (tab === 'week') {
        // This week so far: Sunday → today
        const now = new Date();
        const sunday = new Date(now); sunday.setDate(now.getDate() - now.getDay());
        const todayStr = ymd(now);
        const slots = [], cur = new Date(sunday);
        while (ymd(cur) <= todayStr) {
          const s = ymd(cur);
          slots.push(map[s] || empty(s));
          cur.setDate(cur.getDate() + 1);
        }
        return slots;
      }
      if (tab === 'month') {
        // This month so far: 1st → today
        const now = new Date();
        const y = now.getFullYear(), m = now.getMonth();
        const slots = [];
        for (let i = 1; i <= now.getDate(); i++) {
          const s = `${y}-${String(m+1).padStart(2,'0')}-${String(i).padStart(2,'0')}`;
          slots.push(map[s] || empty(s));
        }
        return slots;
      }
      // custom: fill every day if range ≤ 62 days
      if (this.customFrom && this.customTo) {
        const start = new Date(this.customFrom + 'T00:00:00');
        const end   = new Date(this.customTo   + 'T00:00:00');
        if (Math.round((end - start) / 86400000) + 1 <= 62) {
          const slots = [], cur = new Date(start);
          while (cur <= end) {
            const s = cur.toISOString().slice(0, 10);
            slots.push(map[s] || empty(s));
            cur.setDate(cur.getDate() + 1);
          }
          return slots;
        }
      }
      return daily;
    },
    maxDaily(tab) {
      return Math.max(1, ...this.paddedDailyData(tab).map(d => d.total || 0));
    },
    dailyPct(val, tab) {
      if (!val) return 0;
      return Math.max(2, (val / this.maxDaily(tab)) * 100);
    },
    dailyLabel(dateStr) {
      if (!dateStr) return '';
      const d = new Date(dateStr + 'T00:00:00');
      if (isNaN(d.getTime())) return dateStr.slice(5);
      const weekdays = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
      return weekdays[d.getDay()] + ' ' + (d.getMonth()+1) + '/' + d.getDate();
    },

    renderDetails(record) {
      if (!this.schema) return '';
      return renderPayload(this.schema, record);
    },
  };
}
