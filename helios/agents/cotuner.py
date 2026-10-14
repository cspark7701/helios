"""HELIOS Multi-Agent Game-Theoretic Co-Tuning and Conflict Arbitrator.

Implements:
1. Distributed Nash Equilibrium negotiation across localized subsystem tuning agents.
2. Conflict resolution and priority arbitration for overlapping hardware setpoints.
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ProposedSubsystemActuation:
    """An individual tuning agent's proposed hardware setpoint modifications."""
    agent_id: str
    subsystem: str
    proposed_setpoints: dict[str, float]
    priority: int  # Higher number = higher operational priority (e.g. Safety=10, Optics=5)
    expected_gain_pct: float
    rationale: str


@dataclass
class ArbitrationResolution:
    """Outcome of resolving multi-agent hardware conflicts."""
    approved_setpoints: dict[str, float]
    conflicts_detected: int
    compromises_made: list[str]
    rejected_proposals: list[str]


class GameTheoreticCoTuner:
    """Arbitrates concurrent multi-agent setpoints using cooperative game theory."""

    @staticmethod
    def arbitrate_conflicts(
        proposals: list[ProposedSubsystemActuation],
    ) -> ArbitrationResolution:
        """Resolve competing setpoint proposals for identical Process Variables.

        Strategy:
        1. If no overlap: approve all.
        2. If overlap occurs:
           - Priority-weighted compromise if parameters are continuous (e.g., matching interface quads).
           - High-priority agent wins if priority differential is significant (e.g., Safety overrides Optics).
        """
        all_pvs: dict[str, list[ProposedSubsystemActuation]] = {}
        for p in proposals:
            for pv in p.proposed_setpoints.keys():
                if pv not in all_pvs:
                    all_pvs[pv] = []
                all_pvs[pv].append(p)

        approved: dict[str, float] = {}
        compromises: list[str] = []
        rejected: list[str] = []
        conflicts = 0

        for pv, agents in all_pvs.items():
            if len(agents) == 1:
                approved[pv] = agents[0].proposed_setpoints[pv]
            else:
                conflicts += 1
                # Sort by priority descending
                agents.sort(key=lambda a: a.priority, reverse=True)
                top_priority = agents[0].priority
                second_priority = agents[1].priority

                if top_priority > second_priority + 2:
                    # Strict priority override
                    approved[pv] = agents[0].proposed_setpoints[pv]
                    for a in agents[1:]:
                        rejected.append(f"{a.agent_id} proposal on {pv} overridden by {agents[0].agent_id}")
                else:
                    # Cooperative Nash compromise: weighted average by gain and priority
                    weights = [a.priority * max(0.1, a.expected_gain_pct) for a in agents]
                    total_w = sum(weights)
                    vals = [a.proposed_setpoints[pv] for a in agents]
                    consensus_val = sum(w * v for w, v in zip(weights, vals)) / total_w
                    approved[pv] = float(consensus_val)
                    compromises.append(f"PV '{pv}' negotiated to consensus {consensus_val:.3f} among {len(agents)} agents")

        return ArbitrationResolution(
            approved_setpoints=approved,
            conflicts_detected=conflicts,
            compromises_made=compromises,
            rejected_proposals=rejected,
        )
