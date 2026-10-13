#!/usr/bin/env python3
"""
Generate a professional, high-resolution architecture and dataflow diagram
illustrating the integration of synapticTrack and RAON into HELIOS.
Follows the clean visual styling of docs/manual/architecture.png.
"""

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

def create_integration_diagram(output_path="docs/integration_synaptictrack_raon.png"):
    fig, ax = plt.subplots(figsize=(16, 12), dpi=300)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")

    fig.patch.set_facecolor("#f8fafc")
    ax.set_facecolor("#f8fafc")

    # Colors
    c_header = "#0f172a"
    c_st_bg = "#eff6ff"          # Soft blue (synapticTrack)
    c_st_border = "#2563eb"
    c_st_text = "#1d4ed8"

    c_raon_bg = "#fdf4ff"        # Soft fuchsia/purple (raon private)
    c_raon_border = "#c026d3"
    c_raon_text = "#a21caf"

    c_helios_bg = "#f0fdf4"      # Soft emerald green (HELIOS host)
    c_helios_border = "#16a34a"
    c_helios_text = "#15803d"

    c_twin_bg = "#fff7ed"        # Soft orange (Digital Twin & Surrogate)
    c_twin_border = "#ea580c"
    c_twin_text = "#c2410c"

    c_ops_bg = "#fef2f2"         # Soft red (Safety & Hardware Control)
    c_ops_border = "#dc2626"
    c_ops_text = "#b91c1c"

    shadow_color = "#cbd5e1"

    def draw_card(x, y, w, h, bg, border, title, items=None, subtitle=None, title_color="#0f172a"):
        shadow = FancyBboxPatch((x + 0.35, y - 0.35), w, h, boxstyle="round,pad=0.25,rounding_size=1.0",
                                facecolor=shadow_color, edgecolor="none", alpha=0.45, zorder=2)
        ax.add_patch(shadow)
        box = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.25,rounding_size=1.0",
                             facecolor=bg, edgecolor=border, linewidth=2.0, zorder=3)
        ax.add_patch(box)

        if subtitle:
            ax.text(x + w/2, y + h - 1.6, title, ha="center", va="center",
                    fontsize=12.2, fontweight="bold", color=title_color, zorder=4)
            ax.text(x + w/2, y + h - 3.2, subtitle, ha="center", va="center",
                    fontsize=9.2, fontstyle="italic", color="#475569", zorder=4)
        else:
            ax.text(x + w/2, y + h - 1.8, title, ha="center", va="center",
                    fontsize=11.5, fontweight="bold", color=title_color, zorder=4)

        if items:
            start_y = y + h - 5.0 if subtitle else y + h - 3.6
            for i, itm in enumerate(items):
                ax.text(x + 1.8, start_y - i * 2.3, f"• {itm}", ha="left", va="center",
                        fontsize=9.3, color="#1e293b", zorder=4)

    # 1. Header Banner
    ax.text(50, 97.5, "HELIOS Integration Architecture", ha="center", va="center",
            fontsize=22, fontweight="bold", color=c_header)
    ax.text(50, 95.2, "Linking synapticTrack (Core ML) and RAON (Facility Digital Twin) into HELIOS Orchestrator",
            ha="center", va="center", fontsize=11.5, color="#475569")

    # Section Top: Two Source Repositories Side by Side (y=72.0 to 92.5)
    # Left: synapticTrack
    draw_card(4, 73.0, 44.5, 19.5, c_st_bg, c_st_border,
              "synapticTrack (Machine-Neutral Core)",
              subtitle="~/Work/simulation_codes-working/synapticTrack • Open Python Library",
              title_color=c_st_text)

    st_boxes = [
        ("PyTorch Regressor Engine", "MLPRegressor, LeakyReLU\nPhysics-regularized loss terms", 5.8, 74.2, 19.5),
        ("Normalization & Layouts", "NormalizationBundle, OutputLayout\nStrict unit & dimension contracts", 27.0, 74.2, 19.5),
        ("Frozen Surrogate Contract", "FrozenSurrogateInterface\nDifferentiable ∇_u y_pred tensors", 5.8, 80.5, 19.5),
        ("Sampling & TRACK Adapters", "30-bit Sobol / LHS samplers\nOwnedWorkspace TRACK runtimes", 27.0, 80.5, 19.5),
    ]
    for b_title, b_desc, bx, by, bw in st_boxes:
        box_p = FancyBboxPatch((bx, by), bw, 4.6, boxstyle="round,pad=0.2,rounding_size=0.6",
                               facecolor="#ffffff", edgecolor=c_st_border, linewidth=1.2, zorder=5)
        ax.add_patch(box_p)
        ax.text(bx + bw/2, by + 3.1, b_title, ha="center", va="center",
                fontsize=9.2, fontweight="bold", color=c_st_text, zorder=6)
        ax.text(bx + bw/2, by + 1.4, b_desc, ha="center", va="center",
                fontsize=7.8, color="#475569", multialignment="center", zorder=6)

    # Right: raon private workspace
    draw_card(51.5, 73.0, 44.5, 19.5, c_raon_bg, c_raon_border,
              "RAON Private Workspace (Target Facility)",
              subtitle="~/Work/projects/raon • Confidential Facility Digital Twin Assets",
              title_color=c_raon_text)

    raon_boxes = [
        ("Lattice Decks (LEBT / MEBT)", "track.dat, 3D field maps\nIRIS accelerator geometries", 53.3, 74.2, 19.5),
        ("Trained Surrogate Checkpoint", "50k-sample best_model.pt\nartifact_manifest.json (SHA-256)", 74.5, 74.2, 19.5),
        ("LEBTSurrogateModel Adapter", "raon_adapters.lebt.ml.surrogate\nReal-time normalized & physical APIs", 53.3, 80.5, 19.5),
        ("Production PV Bindings", "Channel Access PV manifests\nEmpirical calibration datasets", 74.5, 80.5, 19.5),
    ]
    for b_title, b_desc, bx, by, bw in raon_boxes:
        box_p = FancyBboxPatch((bx, by), bw, 4.6, boxstyle="round,pad=0.2,rounding_size=0.6",
                               facecolor="#ffffff", edgecolor=c_raon_border, linewidth=1.2, zorder=5)
        ax.add_patch(box_p)
        ax.text(bx + bw/2, by + 3.1, b_title, ha="center", va="center",
                fontsize=9.2, fontweight="bold", color=c_raon_text, zorder=6)
        ax.text(bx + bw/2, by + 1.4, b_desc, ha="center", va="center",
                fontsize=7.8, color="#475569", multialignment="center", zorder=6)

    # Section Middle: THE DIGITAL TWIN HOST INTERFACE & SURROGATE LAYER (y=47.5 to 66.5)
    draw_card(4, 48.0, 92, 18.5, c_twin_bg, c_twin_border,
              "HELIOS DIGITAL TWIN & SURROGATE INFERENCE LAYER (helios.physics.surrogate)",
              subtitle="Hybrid In-Process Plugin Provider • High-Speed Pre-Flight Verification (<2 ms) • RL Simulation Dynamics",
              title_color=c_twin_text)

    twin_subboxes = [
        ("RaonFacilityPlugin", "Dynamic loader in helios\nAuto-detects raon models\nLoads best_model.pt directly", 6.5, 49.5, 20.0),
        ("Sub-Millisecond Pre-Flight", "Candidate setpoints (ΔI, Δθ)\nEvaluates beam loss & BPM orbit\nEnforces safety envelope checks", 28.5, 49.5, 21.0),
        ("Gymnasium RL Environment", "LinacSurrogateEnv (<1 ms / step)\nAccelerates Actor-Critic training\nby >1,000x vs TRACK ray-tracing", 51.5, 49.5, 21.0),
        ("Differentiable Neural MPC", "Computes analytical ∇_u y_pred\nDirect gradient trajectory descent\nMulti-step receding horizon planning", 74.5, 49.5, 19.5),
    ]
    for tb_title, tb_desc, tbx, tby, tbw in twin_subboxes:
        tbox = FancyBboxPatch((tbx, tby), tbw, 10.5, boxstyle="round,pad=0.2,rounding_size=0.6",
                              facecolor="#ffffff", edgecolor=c_twin_border, linewidth=1.2, zorder=5)
        ax.add_patch(tbox)
        ax.text(tbx + tbw/2, tby + 8.5, tb_title, ha="center", va="center",
                fontsize=9.6, fontweight="bold", color=c_twin_text, zorder=6)
        ax.text(tbx + tbw/2, tby + 4.5, tb_desc, ha="center", va="center",
                fontsize=8.2, color="#475569", multialignment="center", zorder=6)

    # Section Bottom-Middle: HELIOS MULTI-AGENT ORCHESTRATION & OPTIMIZATION (y=24.5 to 41.5)
    draw_card(4, 25.0, 92, 16.5, c_helios_bg, c_helios_border,
              "HELIOS MULTI-AGENT ORCHESTRATOR & OPTIMIZATION PLATFORM",
              subtitle="Plan-First Execution Lifecycle • Osprey Pattern • Autonomous Closed-Loop Tuning",
              title_color=c_helios_text)

    helios_subboxes = [
        ("HELIOS-Orchestrator", "Natural language planning\nDynamic capability classifier\ndocs/exec-plans/ engine", 6.5, 26.5, 20.0),
        ("HELIOS-Tuner (RL & SVD)", "ActorCriticNetwork (PyTorch)\nORM Inversion (SVD pseudoinverse)\nMulti-objective Pareto optimization", 28.5, 26.5, 21.0),
        ("HELIOS-Safety Gatekeeper", "Slew-rate & DAC 0.05 A bounds\nFast MPS differential beam abort\nAtomic rollback stack checkpointing", 51.5, 26.5, 21.0),
        ("HELIOS-Diagnostics", "BPM trajectory reconstruction\nACCT transmission monitoring\nRadiation loss heatmap analysis", 74.5, 26.5, 19.5),
    ]
    for hb_title, hb_desc, hbx, hby, hbw in helios_subboxes:
        hbox = FancyBboxPatch((hbx, hby), hbw, 9.0, boxstyle="round,pad=0.2,rounding_size=0.6",
                              facecolor="#ffffff", edgecolor=c_helios_border, linewidth=1.2, zorder=5)
        ax.add_patch(hbox)
        ax.text(hbx + hbw/2, hby + 7.2, hb_title, ha="center", va="center",
                fontsize=9.5, fontweight="bold", color=c_helios_text, zorder=6)
        ax.text(hbx + hbw/2, hby + 3.8, hb_desc, ha="center", va="center",
                fontsize=8.1, color="#475569", multialignment="center", zorder=6)

    # Section Bottom: OPERATOR UI, CONTROL AGENT & LIVE ACCELERATOR (y=2.5 to 18.5)
    draw_card(4, 2.5, 92, 16.0, c_ops_bg, c_ops_border,
              "OPERATOR INTERFACES, EPICS CONTROL & LIVE RAON HARDWARE",
              subtitle="High-Contrast Web GUI • EPICS CA / PVA Actuation • RAON Superconducting Linac",
              title_color=c_ops_text)

    ops_subboxes = [
        ("Web GUI Dashboard", "FastAPI / WebSocket\nSide-panel prompt window\nInteractive model selector", 6.5, 4.0, 20.0),
        ("HELIOS-Control", "EPICS Channel Access & PVA\nAtomic caput with readback\nTimeout and quench guards", 28.5, 4.0, 21.0),
        ("RAON Hardware (LEBT/MEBT)", "ECR Ion Source, Solenoids\nElectrostatic Chopper (<2.8 µs)\nKicker power supplies (0.168 A/mrad)", 51.5, 4.0, 21.0),
        ("RAON SCL Cryomodules", "QWR / HWR Superconducting RF\nPiezo microphonics tuners\n2.0 K cryogenic plant balancing", 74.5, 4.0, 19.5),
    ]
    for ob_title, ob_desc, obx, oby, obw in ops_subboxes:
        obox = FancyBboxPatch((obx, oby), obw, 8.5, boxstyle="round,pad=0.2,rounding_size=0.6",
                              facecolor="#ffffff", edgecolor=c_ops_border, linewidth=1.2, zorder=5)
        ax.add_patch(obox)
        ax.text(obx + obw/2, oby + 6.8, ob_title, ha="center", va="center",
                fontsize=9.4, fontweight="bold", color=c_ops_text, zorder=6)
        ax.text(obx + obw/2, oby + 3.4, ob_desc, ha="center", va="center",
                fontsize=8.0, color="#475569", multialignment="center", zorder=6)

    # Flow arrows
    # 1. synapticTrack -> Digital Twin (ML definitions & normalization)
    ax.annotate("", xy=(26.25, 66.5), xytext=(26.25, 73.0),
                arrowprops=dict(facecolor=c_st_border, edgecolor="none", width=2.4, headwidth=8, headlength=7, zorder=10))
    ax.text(26.25, 69.8, "PyTorch ML Contracts & Normalizers", ha="center", va="center",
            fontsize=8.5, fontweight="bold", color=c_st_text, bbox=dict(boxstyle="round,pad=0.2", facecolor="#ffffff", edgecolor=c_st_border, linewidth=0.8, zorder=11))

    # 2. raon -> Digital Twin (Trained Checkpoints & LEBTSurrogateModel)
    ax.annotate("", xy=(73.75, 66.5), xytext=(73.75, 73.0),
                arrowprops=dict(facecolor=c_raon_border, edgecolor="none", width=2.4, headwidth=8, headlength=7, zorder=10))
    ax.text(73.75, 69.8, "Trained Weights & Lattice Assets", ha="center", va="center",
            fontsize=8.5, fontweight="bold", color=c_raon_text, bbox=dict(boxstyle="round,pad=0.2", facecolor="#ffffff", edgecolor=c_raon_border, linewidth=0.8, zorder=11))

    # 3. Digital Twin -> HELIOS Multi-Agent (Fast Validation & RL gym steps)
    ax.annotate("", xy=(50, 41.5), xytext=(50, 48.0),
                arrowprops=dict(facecolor=c_twin_border, edgecolor="none", width=2.6, headwidth=8, headlength=7, zorder=10))
    ax.text(50, 44.8, "Sub-Millisecond Pre-Flight Validation (<2 ms) & RL Transitions", ha="center", va="center",
            fontsize=8.8, fontweight="bold", color=c_twin_text, bbox=dict(boxstyle="round,pad=0.2", facecolor="#ffffff", edgecolor=c_twin_border, linewidth=0.8, zorder=11))

    # 4. HELIOS Multi-Agent -> Control / Operations (Verified Safe Setpoints)
    ax.annotate("", xy=(50, 18.5), xytext=(50, 25.0),
                arrowprops=dict(facecolor=c_ops_border, edgecolor="none", width=2.6, headwidth=8, headlength=7, zorder=10))
    ax.text(50, 21.8, "Safety-Approved Setpoint Actuation (EPICS CA / PVA)", ha="center", va="center",
            fontsize=8.8, fontweight="bold", color=c_ops_text, bbox=dict(boxstyle="round,pad=0.2", facecolor="#ffffff", edgecolor=c_ops_border, linewidth=0.8, zorder=11))

    plt.tight_layout()
    plt.savefig(output_path, dpi=300, facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close()
    print(f"Integration diagram successfully saved to {output_path}")

if __name__ == "__main__":
    create_integration_diagram()
