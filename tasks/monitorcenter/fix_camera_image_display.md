# Fix: CearTrack — Display Camera Image in Detail View

## Goal
Show the camera test image in the laptop detail panel.
When a technician expands a laptop record, the Camera section shows
the actual captured image so they can judge image quality visually.

## Part 1: Update `modules/laptop/schema.json`

In the `Test Results` status_grid section, remove the camera
`image_quality_check` item (it no longer exists in the JSON).

Update camera items to only show device_status and capture_result:
```json
{"path": "payload.camera.device_status", "label": "Camera"},
{"path": "payload.camera.capture_result", "label": "Capture"}
```

Add a new dedicated camera section BEFORE the Test Results section:

```json
{
  "title": "Camera",
  "type": "camera_image",
  "fields": [
    {"path": "payload.camera.device_status",  "label": "Status"},
    {"path": "payload.camera.driver_type",    "label": "Driver"},
    {"path": "payload.camera.capture_result", "label": "Capture"},
    {"path": "payload.camera.driver_note",    "label": "Note"}
  ],
  "image_path": "payload.camera.image_base64"
}
```

## Part 2: Update `static/js/renderer.js`

Add handler for `camera_image` section type:

```javascript
function renderCameraSection(section, data) {
  const imageB64 = getByPath(data, section.image_path);

  // Key-value fields
  const fields = section.fields.map(f => {
    const value = getByPath(data, f.path) ?? '—';
    return `
      <div class="kv-label">${f.label}</div>
      <div class="kv-value">${value}</div>
    `;
  }).join('');

  // Image display
  let imageHtml = '';
  if (imageB64 && imageB64.length > 100) {
    // Valid base64 image
    imageHtml = `
      <div style="margin-top:12px; grid-column:1/-1;">
        <div class="kv-label" style="margin-bottom:6px;">Captured Image</div>
        <img src="data:image/jpeg;base64,${imageB64}"
             alt="Camera test image"
             style="max-width:320px; max-height:240px; border-radius:4px;
                    border:1px solid var(--border); display:block;
                    cursor:pointer;"
             onclick="this.style.maxWidth=this.style.maxWidth==='100%'?'320px':'100%'"
             title="Click to enlarge">
        <div style="font-size:0.75em; color:var(--text-secondary); margin-top:4px;">
          Click image to enlarge
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
```

In the `renderPayload()` function, add the new case:
```javascript
case "camera_image": return renderCameraSection(section, data);
```

## Part 3: Add CSS for image hover effect in `static/css/dashboard.css`

```css
/* Camera image in detail view */
.detail-panel img {
  transition: max-width 0.2s ease, max-height 0.2s ease;
}
.detail-panel img:hover {
  opacity: 0.9;
}
```

## Verification

1. Upload a laptop JSON that has `camera.image_base64` populated
2. Open CearTrack → Today tab → click on that laptop card to expand
3. Camera section shows:
   - Status / Driver / Capture / Note key-value fields
   - Captured image thumbnail (max 320x240)
   - Click image → expands to full width
   - Click again → shrinks back

4. Upload a laptop JSON with empty `image_base64` (Surface/IPU3):
   - Camera section shows warning message instead of image

5. Verify schema.json change:
   - `image_quality_check` no longer appears in Test Results grid

## Constraints
- Do NOT change any API endpoints or storage logic
- Do NOT modify `modules/laptop/module.py`
- Image click-to-enlarge is pure CSS/JS — no library needed
- `image_base64` field may be empty string — always handle gracefully
- Run `python -m py_compile app.py` to verify no Python changes broke anything
