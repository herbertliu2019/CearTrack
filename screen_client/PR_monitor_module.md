# Monitor test script + CearTrack monitor module

Adds `monitor_test.sh` and a `monitor` module. See `CHANGELOG.md` for the file list.

## Decisions that differ from the task docs

| Task doc | Implemented | Why |
|---|---|---|
| Role × module permissions, viewer/operator/admin | Not built; server acceptance #7 deferred | The platform has no auth yet (agreed) |
| Global `audit_log`, reuse laptop's SN timeline | Module-local `monitor_audit_log`, shown on the detail page | Neither exists in the code (agreed) |
| Admin-only `edid_raw_hex` | Hidden from everyone, kept in `raw_json` | No admin role exists |
| Delete action | Not built; exclude/restore only | No role can be trusted with it yet (agreed) |
| Same storage as laptop | SQLite | Laptop storage keeps one record per SN (agreed) |
| Reuse laptop's list and detail templates | New table and detail pages using shared `dashboard.css` | Laptop has neither page (agreed) |
| "Total tests" stat | Unique SNs, with test runs as a sub-line | Existing rule: count by SN |
| No record without EDID | Operator can mark bad, scan SN, record FAIL (`display.no_signal`, `dead_pixel_count: null`) | Otherwise dead monitors leave no trace (agreed) |
| Mark ethernet BAD like laptop | Must have link to start, or quit | A station fault must not fail a monitor |

Additions beyond the docs: a "picture showing?" prompt in step 4, a check that the cable really moved in step 6, a warning when the previous monitor is still connected, and `identity.edid_decode_text` in the report.

## Self-test

**Nothing here has run on real hardware.** The script ran against a fake `/sys/class/drm` and a stubbed `xrandr`, with the pattern window stubbed and reports uploaded to a local Flask server using a temp data dir. The Tk pattern code ran separately in a small window on Windows. Wipe, CPU, Mem and Cyclelution integrations were stubbed for the server run.

Results: 75 script checks and all server checks pass.

### Script scenarios (TASK_monitor_test.md §4)

| # | Scenario | Simulated | Real hardware |
|---|---|---|---|
| 1 | LG 27UD58, DP + HDMI×2, all good | PASS, record on server | Not run |
| 2 | Station HDMI at 4K30 | WARN, `station_limited=true` | Not run |
| 3 | 2 dead pixels | PASS | n/a |
| 4 | 3 dead pixels | FAIL, `dead pixels 3 > 2` | n/a |
| 5 | Cosmetic f + crack | FAIL, defect recorded | n/a |
| 6 | SN mismatch / no EDID serial | Continues, WARN | Not run (LG serial unconfirmed) |
| 7 | Different monitor on port swap | Warns, not PASS | Not run |
| 8 | No adapter, `n` | NOT_TESTED, WARN | n/a |
| 9 | Upload fails, then recovers | pending/, sent/ on next run | Network unplug not run; simulated with a closed port |
| 10 | 3 monitors in a row | Operator asked once, 3 reports | Not run |
| 11 | Internal screen / two externals | Excluded / asks for one cable | Not run |
| 12 | Tampered overall_result | Server result kept, mismatch logged | n/a |
| 13 | Wayland | Explains Xorg, exits 1 | Detection via env tested; logind path not run |

### Server scenarios (TASK_ceartrack_monitor_module.md §9)

| # | Check | Result |
|---|---|---|
| 1 | Seed, list, stats, filters, search, paging | Pass (API); list page checked in a browser |
| 2 | Visual match with laptop; laptop unchanged | Partial: list and top of detail viewed. No before/after laptop screenshots; laptop gains only the nav link |
| 3 | 3 dead pixels red, reason shown | Pass |
| 4 | Tampered result | Pass |
| 5 | Duplicate upload | Pass |
| 6 | Latest-only toggle | Pass |
| 7 | Roles | **Not done** (no auth) |
| 8 | Upload, export, exclude in audit log and timeline | Pass |
| 9 | CSV with UTF-8 BOM | Pass (bytes checked, not opened in Excel) |
| 10 | `/monitor/version.txt` matches script | Pass |

## To verify on the station

- [ ] Xorg session, root access to X, Tk keyboard capture in the pattern window
- [ ] Real `xrandr` output maps to the right output; 4K60 mode is applied
- [ ] LG 27UD58: does EDID `0xFF` equal `906NTZN4G765`?
- [ ] LG 27UD58: is the EDID fingerprint the same on DP and both HDMI ports? If not, step 6 will not PASS those ports
- [ ] `edid-decode` and `python3-tk` install on the Live USB

## Open items for Herbert

1. Cyclelution Size, Color and Mark lists for monitors
2. Station model; can its DP/HDMI run 4K60?
3. Should a port FAIL fail the whole monitor? (currently yes)
4. Align the test plan wording "No dead pixel" with the real "fewer than 3" standard

🤖 Generated with [Claude Code](https://claude.com/claude-code)
