# Execution Plan / Change Record: 00021

- **Sub-tasks**: Phase 13 Live Web Dashboard & Real-Time Visualization (13.1, 13.2, 13.3)
- **Status**: Completed
- **Date**: 2026-10-13
- **Author**: Chong Shik Park / HELIOS Team
- **Reference**: LBNL Osprey Framework, FastAPI, Real-Time Accelerator Visualization

---

## 1. Objectives

- Implement a real-time web-based operator console with a FastAPI backend and embedded dark-mode control room dashboard.
- Provide real-time REST and WebSocket endpoints for streaming live linac telemetry, beam transmission, BPM orbits, and BLM radiation.
- Implement data structures and formatting for accelerator physics plots:
  - RMS orbit distortion vs golden orbit and tolerance bands.
  - 3-sigma beam envelope ($\sigma_x, \sigma_y$) vs vacuum chamber physical aperture.
  - Beam loss monitor (BLM) radiation heatmap and loss hotspot localization.
- Provide Human-in-the-Loop plan review, approval (`/api/plans/{id}/approve`), and one-click emergency panic shutdown (`/api/emergency/panic`).
- Add `helios dashboard` command to the Typer CLI.

---

## 2. Implementation Summary

1. **Dashboard App Backend (`helios/dashboard/app.py`)**:
   - `create_dashboard_app`: Creates FastAPI application serving both REST API and single-page HTML console.
   - Endpoints:
     - `GET /`: Single-page dark-mode web console.
     - `GET /api/status`: Global linac health, interlocks, autonomy level.
     - `GET /api/telemetry`: Transmission, beam current, BPM readings, BLM loss.
     - `GET /api/plots/orbit`, `/api/plots/envelope`, `/api/plots/blm`: Structured datasets for physics charting.
     - `GET /api/plans`, `POST /api/plans/{id}/approve`, `POST /api/plans/{id}/reject`: Plan review and approval gating.
     - `POST /api/emergency/panic`: One-click panic shutdown trigger.
     - `WebSocket /ws/telemetry`: Streaming telemetry feed for connected frontends.
2. **Physics Plot Generators (`helios/dashboard/plots.py`)**:
   - `generate_orbit_plot_data`: Trajectory along $s$, comparison against golden orbit, and tolerance limits.
   - `generate_envelope_plot_data`: 3-sigma bounds ($\pm 3\sigma_x, \pm 3\sigma_y$) and aperture boundary lines.
   - `generate_blm_heatmap_data`: Spatial radiation loss profile and hotspot detection.
3. **CLI Command (`helios/cli/main.py`)**:
   - Added `helios dashboard` Typer command (`--host`, `--port`, `--reload`) launching Uvicorn server.
4. **Testing**:
   - Built test suite in `tests/test_dashboard.py` covering HTML rendering, status, telemetry, plot endpoints, plan approval, and panic execution.
   - All 66 tests passing in the `helios` conda environment.

---

## 3. Files Modified / Created

- `M  docs/exec-plans/active/00014_next_development_phases_tasklist.md`
- `A  docs/exec-plans/completed/00021_phase13_web_dashboard_and_visualization.md`
- `M  helios/cli/main.py`
- `A  helios/dashboard/__init__.py`
- `A  helios/dashboard/app.py`
- `A  helios/dashboard/plots.py`
- `A  tests/test_dashboard.py`
