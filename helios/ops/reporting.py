"""HELIOS Commissioning and Shift Handover Report Generator.

Compiles executed plans, orbit improvements, beam transmission statistics,
and anomaly events into Markdown and LaTeX reports for accelerator logbooks.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from helios.core.schemas import ExecutionPlan

logger = logging.getLogger(__name__)


@dataclass
class ShiftSummaryData:
    """Consolidated operational metrics for a commissioning shift."""
    shift_label: str
    physicist_on_duty: str
    facility_name: str
    start_time: datetime
    end_time: datetime
    executed_plans_count: int
    initial_orbit_rms_mm: float
    final_orbit_rms_mm: float
    initial_transmission_pct: float
    final_transmission_pct: float
    total_anomalies_detected: int
    interlocks_tripped_count: int
    notes: str = ""


class CommissioningReportGenerator:
    """Generates standardized shift handover documents in Markdown and LaTeX formats."""

    @staticmethod
    def generate_markdown_report(
        data: ShiftSummaryData,
        plans: list[ExecutionPlan] | None = None,
    ) -> str:
        """Render commissioning shift handover report in GitHub-flavored Markdown."""
        orbit_improvement = (
            ((data.initial_orbit_rms_mm - data.final_orbit_rms_mm) / max(1e-4, data.initial_orbit_rms_mm)) * 100.0
        )
        trans_gain = data.final_transmission_pct - data.initial_transmission_pct

        lines = [
            f"# HELIOS Commissioning Shift Report: {data.shift_label}",
            "",
            f"- **Facility**: {data.facility_name}",
            f"- **Physicist on Duty**: {data.physicist_on_duty}",
            f"- **Shift Duration**: {data.start_time.strftime('%Y-%m-%d %H:%M')} to {data.end_time.strftime('%Y-%m-%d %H:%M')} UTC",
            f"- **Report Generated**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC",
            "",
            "---",
            "",
            "## 📊 Shift Performance Summary",
            "",
            "| Metric | Shift Start | Shift End | Delta / Gain |",
            "| :--- | :---: | :---: | :---: |",
            f"| **Orbit Distortion (RMS)** | `{data.initial_orbit_rms_mm:.3f} mm` | `{data.final_orbit_rms_mm:.3f} mm` | **{orbit_improvement:+.1f}%** |",
            f"| **Beam Transmission** | `{data.initial_transmission_pct:.1f}%` | `{data.final_transmission_pct:.1f}%` | **{trans_gain:+.1f}%** |",
            f"| **Executed Plans** | - | - | `{data.executed_plans_count}` plans |",
            f"| **Anomalies / MPS Trips** | - | - | `{data.total_anomalies_detected}` / `{data.interlocks_tripped_count}` |",
            "",
            "---",
            "",
            "## 🚀 Plan Execution Log",
            "",
        ]

        if plans:
            lines.append("| Plan ID | Title | Objective | Autonomy Level | State |")
            lines.append("| :--- | :--- | :--- | :---: | :---: |")
            for p in plans:
                lines.append(f"| `{p.plan_id}` | **{p.title}** | {p.objective} | `{p.autonomy_level.value}` | `{p.state.value}` |")
        else:
            lines.append("*(No structured execution plans attached)*")

        lines.extend([
            "",
            "---",
            "",
            "## 📝 Operator Notes & Handover Recommendations",
            "",
            data.notes or "Machine left in stable golden orbit configuration. Normal routine monitoring advised.",
            "",
        ])

        return "\n".join(lines)

    @staticmethod
    def generate_latex_report(data: ShiftSummaryData) -> str:
        """Render formal LaTeX shift handover document."""
        return rf"""\documentclass[11pt,a4paper]{{article}}
\usepackage[utf8]{{inputenc}}
\usepackage{{geometry}}
\usepackage{{booktabs}}
\usepackage{{hyperref}}
\geometry{{margin=1in}}

\title{{\textbf{{HELIOS Commissioning Shift Handover Report}}\\\large {data.facility_name} --- {data.shift_label}}}
\author{{{data.physicist_on_duty}}}
\date{{{data.end_time.strftime('%B %d, %Y')}}}

\begin{{document}}
\maketitle

\section{{Executive Summary}}
During the operational shift, HELIOS executed autonomous beam steering, transverse envelope matching, and anomaly monitoring.

\begin{{table}}[h]
\centering
\begin{{tabular}}{{lccc}}
\toprule
\textbf{{Metric}} & \textbf{{Start}} & \textbf{{End}} & \textbf{{Outcome}} \\
\midrule
Orbit Distortion (RMS) & {data.initial_orbit_rms_mm:.3f}\,mm & {data.final_orbit_rms_mm:.3f}\,mm & Flattened \\
Beam Transmission & {data.initial_transmission_pct:.1f}\,\% & {data.final_transmission_pct:.1f}\,\% & Optimized \\
Executed Plans & --- & --- & {data.executed_plans_count} completed \\
MPS Interlock Trips & --- & --- & {data.interlocks_tripped_count} \\
\bottomrule
\end{{tabular}}
\caption{{Commissioning performance metrics for shift {data.shift_label}.}}
\end{{table}}

\section{{Operational Notes}}
{data.notes or 'Machine operating nominally within tolerance bounds.'}

\end{{document}}
"""
