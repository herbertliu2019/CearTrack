function getByPath(obj, path) {
  return path.split('.').reduce((acc, key) => acc?.[key], obj);
}

function statusClass(value) {
  if (value === "PASS") return "pass";
  if (value === "FAIL") return "fail";
  if (["WARNING", "HARDWARE_DETECTED", "DATA_UNAVAILABLE"].includes(value)) return "warn";
  return "skip";
}

function renderField(field, data) {
  const value = getByPath(data, field.path);
  const display = (value === null || value === undefined || value === "") ? "—" : value + (field.suffix || "");
  return `
    <div class="kv-label">${field.label}</div>
    <div class="kv-value">${display}</div>
  `;
}

function renderKeyValueSection(section, data) {
  const rows = section.fields.map(f => renderField(f, data)).join("");
  return `
    <div class="detail-section">
      <h3>${section.title}</h3>
      <div class="kv-grid">${rows}</div>
    </div>
  `;
}

function renderStatusGridSection(section, data) {
  const items = section.items.map(item => {
    const value = getByPath(data, item.path) ?? "—";
    return `
      <div class="status-item ${statusClass(value)}">
        <span>${item.label}</span>
        <span>${value}</span>
      </div>
    `;
  }).join("");
  return `
    <div class="detail-section">
      <h3>${section.title}</h3>
      <div class="status-grid">${items}</div>
    </div>
  `;
}

function renderListSection(section, data) {
  const list = getByPath(data, section.path) || [];
  const items = list.map(item => {
    let line = section.item_template;
    Object.entries(item).forEach(([k, v]) => {
      line = line.replace(`{${k}}`, v ?? "—");
    });
    return `<div class="kv-value">${line}</div>`;
  }).join("");
  return `
    <div class="detail-section">
      <h3>${section.title}</h3>
      ${items || '<div class="kv-label">No items</div>'}
    </div>
  `;
}

function renderCameraSection(section, data) {
  const imageB64 = getByPath(data, section.image_path);

  const fields = section.fields.map(f => {
    const value = getByPath(data, f.path) ?? '—';
    return `
      <div class="kv-label">${f.label}</div>
      <div class="kv-value">${value}</div>
    `;
  }).join('');

  let imageHtml = '';
  if (imageB64 && imageB64.length > 100) {
    imageHtml = `
      <div style="margin-top:12px; grid-column:1/-1;">
        <div class="kv-label" style="margin-bottom:6px;">Captured Image</div>
        <img src="data:image/jpeg;base64,${imageB64}"
             alt="Camera test image"
             data-zoomed="0"
             style="max-width:160px; max-height:120px; width:auto; height:auto;
                    border-radius:4px; border:1px solid var(--border);
                    display:block; cursor:pointer;"
             onclick="if (this.dataset.zoomed === '1') {
                        this.style.maxWidth='160px'; this.style.maxHeight='120px';
                        this.dataset.zoomed='0';
                      } else {
                        this.style.maxWidth='none'; this.style.maxHeight='none';
                        this.dataset.zoomed='1';
                      }"
             title="Click to view at original size">
        <div style="font-size:0.75em; color:var(--text-secondary); margin-top:4px;">
          Click image to view at original size
        </div>
      </div>
    `;
  } else if (getByPath(data, 'payload.camera.device_status') === 'HARDWARE_DETECTED') {
    imageHtml = `
      <div style="margin-top:12px; grid-column:1/-1; color:var(--warn);
                  font-size:0.85em;">
        ⚠ Camera hardware detected but driver failed — image not available
      </div>
    `;
  } else if (getByPath(data, 'payload.camera.capture_result') === 'CAPTURE_FAILED') {
    imageHtml = `
      <div style="margin-top:12px; grid-column:1/-1; color:var(--fail);
                  font-size:0.85em;">
        ✗ Image capture failed
      </div>
    `;
  } else {
    imageHtml = `
      <div style="margin-top:12px; grid-column:1/-1; color:var(--text-secondary);
                  font-size:0.85em;">
        No image available
      </div>
    `;
  }

  return `
    <div class="detail-section">
      <h3>${section.title}</h3>
      <div class="kv-grid">
        ${fields}
        ${imageHtml}
      </div>
    </div>
  `;
}

function renderPayload(schema, data) {
  return schema.sections.map(section => {
    switch (section.type) {
      case "key_value": return renderKeyValueSection(section, data);
      case "status_grid": return renderStatusGridSection(section, data);
      case "list": return renderListSection(section, data);
      case "camera_image": return renderCameraSection(section, data);
      default: return `<div>Unknown section type: ${section.type}</div>`;
    }
  }).join("");
}
