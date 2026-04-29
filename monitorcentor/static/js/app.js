function dashboardApp(moduleName) {
  return {
    moduleName,
    activeTab: "latest",
    schema: null,
    latest: [],
    stats: {},
    searchQuery: "",
    searchResults: [],
    expandedKeys: new Set(),
    pollInterval: null,
    currentPage: 1,
    pageSize: 20,

    // Statistics state
    statsRange: 'week',
    statsFrom: '',
    statsTo: '',
    statsData: null,
    statsExpandedKeys: new Set(),

    async init() {
      const r = await fetch(`/${this.moduleName}/api/schema`);
      this.schema = await r.json();
      await this.loadLatest();
      await this.loadStats();
      this.pollInterval = setInterval(() => {
        if (this.activeTab === "latest") this.loadLatest();
      }, 10000);

      const snParam = new URLSearchParams(window.location.search).get("sn");
      if (snParam) {
        this.searchQuery = snParam;
        this.activeTab = "search";
        await this.runSearch();
      }
    },

    async loadLatest() {
      const r = await fetch(`/${this.moduleName}/api/latest`);
      this.latest = await r.json();
      const maxPage = Math.max(1, this.totalPages());
      if (this.currentPage > maxPage) this.currentPage = maxPage;
    },

    totalPages() {
      return Math.max(1, Math.ceil(this.latest.length / this.pageSize));
    },

    paginatedLatest() {
      const start = (this.currentPage - 1) * this.pageSize;
      return this.latest.slice(start, start + this.pageSize);
    },

    pageRangeLabel() {
      if (this.latest.length === 0) return "0";
      const start = (this.currentPage - 1) * this.pageSize + 1;
      const end = Math.min(this.currentPage * this.pageSize, this.latest.length);
      return `${start}–${end} of ${this.latest.length}`;
    },

    goToPage(n) {
      const total = this.totalPages();
      if (n < 1) n = 1;
      if (n > total) n = total;
      this.currentPage = n;
    },

    nextPage() { this.goToPage(this.currentPage + 1); },
    prevPage() { this.goToPage(this.currentPage - 1); },

    async loadStats() {
      const r = await fetch(`/${this.moduleName}/api/stats`);
      this.stats = await r.json();
    },

    async runSearch() {
      if (!this.searchQuery.trim()) { this.searchResults = []; return; }
      const r = await fetch(`/${this.moduleName}/api/search?sn=${encodeURIComponent(this.searchQuery.trim())}`);
      this.searchResults = await r.json();
    },

    toggleExpand(key) {
      if (this.expandedKeys.has(key)) {
        this.expandedKeys.delete(key);
      } else {
        this.expandedKeys.add(key);
      }
      this.expandedKeys = new Set(this.expandedKeys);
    },

    isExpanded(key) {
      return this.expandedKeys.has(key);
    },

    statusClass(value) { return statusClass(value); },

    renderDetails(record) {
      if (!this.schema) return "";
      return renderPayload(this.schema, record);
    },

    miniStatusItems(record) {
      const p = record.payload || {};
      return [
        { label: "Screen", value: p.screen?.dead_pixel_check },
        { label: "Cam",    value: p.camera?.device_status },
        { label: "Audio",  value: p.audio?.speaker_quality_check },
        { label: "KB",     value: p.keyboard?.keys_check },
        { label: "Net",    value: p.network?.internet_test },
        { label: "Batt",   value: p.battery?.status },
        { label: "Kernel", value: p.kernel_health?.status },
      ];
    },

    async loadStatsRange() {
      let url = `/${this.moduleName}/api/stats/range?`;
      if (this.statsRange === 'week') {
        url += 'range=week';
      } else if (this.statsRange === 'month') {
        url += 'range=month';
      } else {
        if (!this.statsFrom || !this.statsTo) return;
        url += `from=${this.statsFrom}&to=${this.statsTo}`;
      }
      const r = await fetch(url);
      this.statsData = await r.json();
      this.statsExpandedKeys = new Set();
    },

    toggleStatsExpand(key) {
      if (this.statsExpandedKeys.has(key)) {
        this.statsExpandedKeys.delete(key);
      } else {
        this.statsExpandedKeys.add(key);
      }
      this.statsExpandedKeys = new Set(this.statsExpandedKeys);
    },

    isStatsExpanded(key) {
      return this.statsExpandedKeys.has(key);
    },

    formatDateRange(from, to) {
      if (!from || !to) return '';
      const fmt = (d) => {
        const parts = d.split('-');
        return `${parts[1]}.${parts[2]}`;
      };
      return `(${fmt(from)} - ${fmt(to)})`;
    },

    cardSpecs(record) {
      const p = record.payload || {};
      return {
        cpu: p.cpu?.model || "—",
        memory: `${p.memory?.total_gb || "?"} GB ${p.memory?.type || ""}`,
        battery: p.battery?.health_percent ? `${p.battery.health_percent}%` : "—",
      };
    },
  };
}
