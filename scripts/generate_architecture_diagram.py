#!/usr/bin/env python3
"""
Generate a professional, high-resolution architecture diagram for HELIOS,
aligned with LBNL Osprey style (clean layered blocks, clear flow arrows,
subsystem breakdowns, and professional color palette).
"""

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

def create_helios_architecture_diagram(output_path="docs/manual/architecture.png"):
    fig, ax = plt.subplots(figsize=(16, 12), dpi=300)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")

    fig.patch.set_facecolor("#f8fafc")
    ax.set_facecolor("#f8fafc")

    # Colors
    c_header = "#0f172a"
    c_user_bg = "#f0f9ff"       # Light sky blue
    c_user_border = "#0284c7"
    c_user_text = "#0369a1"

    c_orch_bg = "#faf5ff"       # Light purple
    c_orch_border = "#7c3aed"
    c_orch_text = "#6d28d9"

    c_agent_bg = "#f0fdf4"      # Light green
    c_agent_border = "#16a34a"
    c_agent_text = "#15803d"

    c_safety_bg = "#fef2f2"     # Light red/rose
    c_safety_border = "#dc2626"
    c_safety_text = "#b91c1c"

    c_ctrl_bg = "#fff7ed"       # Light orange
    c_ctrl_border = "#ea580c"
    c_ctrl_text = "#c2410c"

    c_hw_bg = "#f8fafc"         # Slate gray
    c_hw_border = "#475569"
    c_hw_text = "#334155"

    shadow_color = "#cbd5e1"

    def draw_card(x, y, w, h, bg, border, title, items=None, subtitle=None, title_color="#0f172a"):
        # Shadow
        shadow = FancyBboxPatch((x + 0.35, y - 0.35), w, h, boxstyle="round,pad=0.25,rounding_size=1.0",
                                facecolor=shadow_color, edgecolor="none", alpha=0.45, zorder=2)
        ax.add_patch(shadow)
        # Main box
        box = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.25,rounding_size=1.0",
                             facecolor=bg, edgecolor=border, linewidth=2.0, zorder=3)
        ax.add_patch(box)

        # Title & Subtitle positioning
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
    ax.text(50, 97.5, "HELIOS System Architecture", ha="center", va="center",
            fontsize=22, fontweight="bold", color=c_header)
    ax.text(50, 95.2, "Heavy Ion Linac Intelligent Orchestration Suite • Safety-First Plan-First Multi-Agent Platform",
            ha="center", va="center", fontsize=11.5, color="#475569")

    # Layer 1: OPERATOR & CLIENT INTERFACE (Top, y=82.5 to 92.5)
    draw_card(4, 83.0, 92, 9.5, c_user_bg, c_user_border,
              "OPERATOR INTERFACE & CLIENT LAYER",
              subtitle="Interactive consoles, web dashboards & collaborative human-in-the-loop interfaces",
              title_color=c_user_text)

    client_boxes = [
        ("Web Operator GUI", "FastAPI • High-Contrast UI\nDynamic SVG Orbit / BLM Visualizer", 6, 84.0, 20.5),
        ("Side-Panel Prompt Window", "Interactive Natural Language\nCopilot & In-line Plan Execution", 28.5, 84.0, 21.0),
        ("CLI Commissioning Suite", "tune-orbit • report • audit\nClosed-Loop Trajectory Inversion", 51.5, 84.0, 21.0),
        ("Language Model Selector", "Offline Rules • Ollama (Local)\nOpenAI GPT-4o • Custom Endpoints", 74.5, 84.0, 19.5)
    ]
    for c_title, c_desc, cx, cy, cw in client_boxes:
        c_box = FancyBboxPatch((cx, cy), cw, 4.4, boxstyle="round,pad=0.2,rounding_size=0.6",
                               facecolor="#ffffff", edgecolor=c_user_border, linewidth=1.2, zorder=5)
        ax.add_patch(c_box)
        ax.text(cx + cw/2, cy + 2.9, c_title, ha="center", va="center",
                fontsize=9.6, fontweight="bold", color=c_user_text, zorder=6)
        ax.text(cx + cw/2, cy + 1.3, c_desc, ha="center", va="center",
                fontsize=8.0, color="#475569", multialignment="center", zorder=6)

    # Layer 2: MASTER ORCHESTRATOR & PLAN ENGINE (y=68.5 to 78.5)
    draw_card(4, 69.0, 92, 9.5, c_orch_bg, c_orch_border,
              "MASTER ORCHESTRATOR & PLAN-FIRST ENGINE (HELIOS-Orchestrator)",
              subtitle="LBNL Osprey Alignment • Goal Decomposition • Dynamic Capability Classification • Execution Plan Lifecycle",
              title_color=c_orch_text)

    orch_boxes = [
        ("Natural Language Planner", "Intent classification &\ntask decomposition engine", 6, 70.0, 20.5),
        ("Capability Classifier", "Dynamic skill filtering &\nprompt context minimization", 28.5, 70.0, 21.0),
        ("Execution Plan Engine", "Plan lifecycle:\nDraft → Verified → Executing", 51.5, 70.0, 21.0),
        ("Multi-Agent Coordinator", "Async Pydantic event bus &\nstrongly-typed agent schemas", 74.5, 70.0, 19.5)
    ]
    for o_title, o_desc, ox, oy, ow in orch_boxes:
        o_box = FancyBboxPatch((ox, oy), ow, 4.4, boxstyle="round,pad=0.2,rounding_size=0.6",
                               facecolor="#ffffff", edgecolor=c_orch_border, linewidth=1.2, zorder=5)
        ax.add_patch(o_box)
        ax.text(ox + ow/2, oy + 2.9, o_title, ha="center", va="center",
                fontsize=9.6, fontweight="bold", color=c_orch_text, zorder=6)
        ax.text(ox + ow/2, oy + 1.3, o_desc, ha="center", va="center",
                fontsize=8.0, color="#475569", multialignment="center", zorder=6)

    # Layer 3: SPECIALIZED AGENT ECOSYSTEM (y=47.5 to 64.5)
    agent_w = 21.5
    agent_h = 16.5
    agents_data = [
        (4.0, 48.0, "PHYSICS & SIMULATION", "HELIOS-Physics",
         ["ANL TRACK (Wine 64)", "LBNL IMPACT-Z (PIC)", "Neural Surrogate Models", "RFQ 3D Vane Dynamics", "Linac Vacuum Stripping"],
         c_agent_bg, c_agent_border, c_agent_text),

        (27.5, 48.0, "DIAGNOSTICS & TELEMETRY", "HELIOS-Diagnostics",
         ["BPM Orbit & Centroid", "BLM Radiation Losses", "ACCT Fast Differential", "MENT 2D Tomography", "Laser Tracker Survey"],
         c_agent_bg, c_agent_border, c_agent_text),

        (51.0, 48.0, "OPTIMIZATION & TUNING", "HELIOS-Tuner",
         ["Response Matrix SVD", "Bayesian Optimization", "Reinforcement Learning", "Bunch Chicane $R_{56}$", "Equipartition Hofmann"],
         c_agent_bg, c_agent_border, c_agent_text),

        (74.5, 48.0, "RF & CRYOPLANT DYNAMICS", "HELIOS-RF",
         ["Lorentz Force Detuning", "Piezo FxLMS Feedforward", "Cryoplant Heat Balancing", "Multipactor & Dark Current", "Auto Pulse Conditioning"],
         c_agent_bg, c_agent_border, c_agent_text)
    ]

    for ax_pos, ay_pos, atitle, asub, aitems, abg, aborder, atext in agents_data:
        draw_card(ax_pos, ay_pos, agent_w, agent_h, abg, aborder,
                  atitle, items=aitems, subtitle=asub, title_color=atext)

    # Layer 4: SAFETY GATEKEEPER & VERIFICATION (y=29.0 to 43.5)
    draw_card(4, 29.5, 92, 14.0, c_safety_bg, c_safety_border,
              "SAFETY GATEKEEPER & VERIFICATION HARNESS (HELIOS-Safety)",
              subtitle="Deterministic Gatekeeper • Hardware Boundary Enforcement • Graduated Autonomy Gating",
              title_color=c_safety_text)

    # Human-in-the-Loop badge in Safety Layer (Cleanly placed at y=37.2, below subtitle y=40.3 and above sub-boxes y=30.5 to 36.5)
    hil_box = FancyBboxPatch((32, 37.0), 36, 2.4, boxstyle="round,pad=0.15,rounding_size=0.5",
                             facecolor="#fee2e2", edgecolor="#ef4444", linewidth=1.4, zorder=6)
    ax.add_patch(hil_box)
    ax.text(50, 38.2, "HUMAN-IN-THE-LOOP APPROVAL GATE (Levels 0 – 2)",
            ha="center", va="center", fontsize=9.0, fontweight="bold", color="#991b1b", zorder=7)

    safety_boxes = [
        ("Pre-Flight Simulation", "Validate candidate setpoints\nin Digital Twin before write", 6, 30.5, 20.5),
        ("Hardware Boundaries", "Slew rate clamp, current limits\n0.05 A DAC quantization", 28.5, 30.5, 21.0),
        ("Fast MPS Interlocks", "Sub-5 µs beam abort\nChopper & RF shutoff (<2.8 µs)", 51.5, 30.5, 21.0),
        ("Atomic Rollback Stack", "Instant state restoration\nSHA-256 audit log integrity", 74.5, 30.5, 19.5)
    ]
    for s_title, s_desc, sx, sy, sw in safety_boxes:
        s_box = FancyBboxPatch((sx, sy), sw, 6.0, boxstyle="round,pad=0.2,rounding_size=0.6",
                               facecolor="#ffffff", edgecolor=c_safety_border, linewidth=1.2, zorder=5)
        ax.add_patch(s_box)
        ax.text(sx + sw/2, sy + 4.3, s_title, ha="center", va="center",
                fontsize=9.8, fontweight="bold", color=c_safety_text, zorder=6)
        ax.text(sx + sw/2, sy + 2.0, s_desc, ha="center", va="center",
                fontsize=8.2, color="#475569", multialignment="center", zorder=6)

    # Layer 5: CONTROL & EPICS INTERACTION (y=16.0 to 25.5)
    draw_card(4, 16.5, 92, 9.5, c_ctrl_bg, c_ctrl_border,
              "CONTROL & HARDWARE INTERFACE (HELIOS-Control)",
              subtitle="Protocol-Agnostic Accelerator Communication • Atomic Setpoint Actuation • Telemetry Ingestion",
              title_color=c_ctrl_text)

    ctrl_boxes = [
        ("EPICS Channel Access (CA)", "pyepics client • Semantic\nPV mapping & monitoring", 6, 17.5, 20.5),
        ("EPICS pvAccess (PVA)", "p4p RPC • High-speed\nNTTable & NTNDArray streams", 28.5, 17.5, 21.0),
        ("Readback Verification", "Atomic caget confirmation &\nactuation timeout guards", 51.5, 17.5, 21.0),
        ("Archiver & SoftIOC", "EPICS Archiver Appliance &\nSimulation SoftIOC harness", 74.5, 17.5, 19.5)
    ]
    for ct_title, ct_desc, ctx, cty, ctw in ctrl_boxes:
        ct_box = FancyBboxPatch((ctx, cty), ctw, 4.4, boxstyle="round,pad=0.2,rounding_size=0.6",
                                facecolor="#ffffff", edgecolor=c_ctrl_border, linewidth=1.2, zorder=5)
        ax.add_patch(ct_box)
        ax.text(ctx + ctw/2, cty + 2.9, ct_title, ha="center", va="center",
                fontsize=9.5, fontweight="bold", color=c_ctrl_text, zorder=6)
        ax.text(ctx + ctw/2, cty + 1.3, ct_desc, ha="center", va="center",
                fontsize=8.0, color="#475569", multialignment="center", zorder=6)

    # Layer 6: HEAVY ION LINAC ACCELERATOR HARDWARE (Bottom, y=2.5 to 12.0)
    draw_card(4, 2.5, 92, 9.5, c_hw_bg, c_hw_border,
              "PHYSICAL ACCELERATOR HARDWARE & HIGH-POWER TARGETS",
              subtitle="Heavy Ion Beamlines: LEBT • RFQ • MEBT • Superconducting Linac (SCL) • HEBT",
              title_color=c_hw_text)

    hw_boxes = [
        ("Ion Source & LEBT", "ECR Source, Solenoids\nChopper, Slits, Steerers", 6, 3.5, 17.0),
        ("Radio-Frequency Quadrupole", "4-Vane Structure, RF Drive\nVacuum Cryopumps", 24.5, 3.5, 17.0),
        ("MEBT & Bunchers", "Rebuncher Cavities, Quads\nCollimators, Fast ACCTs", 43.0, 3.5, 17.0),
        ("Superconducting Cavities", "QWR / HWR / Spoke Resonators\nPiezo Tuners, 2 K Cryoplant", 61.5, 3.5, 18.0),
        ("Dumps & Strippers", "Liquid Li Film, 400 kW Dump\nDiamond Loss Monitors", 81.0, 3.5, 13.0)
    ]
    for h_title, h_desc, hx, hy, hw in hw_boxes:
        h_box = FancyBboxPatch((hx, hy), hw, 4.4, boxstyle="round,pad=0.2,rounding_size=0.6",
                               facecolor="#ffffff", edgecolor=c_hw_border, linewidth=1.2, zorder=5)
        ax.add_patch(h_box)
        ax.text(hx + hw/2, hy + 2.9, h_title, ha="center", va="center",
                fontsize=8.8, fontweight="bold", color=c_hw_text, zorder=6)
        ax.text(hx + hw/2, hy + 1.2, h_desc, ha="center", va="center",
                fontsize=7.6, color="#64748b", multialignment="center", zorder=6)

    # Connecting Flow Arrows between layers
    # 1. User -> Orchestrator
    ax.annotate("", xy=(50, 78.5), xytext=(50, 83.0),
                arrowprops=dict(facecolor=c_orch_border, edgecolor="none", width=2.4, headwidth=8, headlength=7, zorder=10))

    # 2. Orchestrator -> Agents
    for target_x in [14.75, 38.25, 61.75, 85.25]:
        ax.annotate("", xy=(target_x, 64.5), xytext=(target_x, 69.0),
                    arrowprops=dict(facecolor=c_agent_border, edgecolor="none", width=2.0, headwidth=7, headlength=6, zorder=10))

    # 3. Agents -> Safety Gatekeeper
    for target_x in [14.75, 38.25, 61.75, 85.25]:
        ax.annotate("", xy=(target_x, 43.5), xytext=(target_x, 48.0),
                    arrowprops=dict(facecolor=c_safety_border, edgecolor="none", width=2.0, headwidth=7, headlength=6, zorder=10))

    # 4. Safety -> Control
    ax.annotate("", xy=(50, 26.0), xytext=(50, 30.0),
                arrowprops=dict(facecolor=c_ctrl_border, edgecolor="none", width=2.4, headwidth=8, headlength=7, zorder=10))

    # 5. Control -> Hardware (Bi-directional: Setpoints down, Telemetry up)
    ax.annotate("", xy=(48, 12.0), xytext=(48, 16.5),
                arrowprops=dict(facecolor=c_hw_border, edgecolor="none", width=2.0, headwidth=7, headlength=6, zorder=10))
    ax.text(45.2, 14.2, "Setpoints", ha="right", va="center", fontsize=8.4, fontweight="bold", color=c_ctrl_text)

    ax.annotate("", xy=(52, 16.5), xytext=(52, 12.0),
                arrowprops=dict(facecolor="#0284c7", edgecolor="none", width=2.0, headwidth=7, headlength=6, zorder=10))
    ax.text(54.8, 14.2, "Telemetry", ha="left", va="center", fontsize=8.4, fontweight="bold", color="#0284c7")

    plt.tight_layout()
    plt.savefig(output_path, dpi=300, facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close()
    print(f"Architecture diagram successfully saved to {output_path}")

if __name__ == "__main__":
    create_helios_architecture_diagram()
