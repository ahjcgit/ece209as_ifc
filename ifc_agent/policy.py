from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .labels import Label, Lattice


@dataclass(frozen=True)
class FlowDecision:
    allowed: bool
    reason: str


class Policy:
    def __init__(
        self,
        lattice: Lattice,
        external_llm_allowed: Iterable[Label],
        user_output_max: Label,
    ) -> None:
        self._lattice = lattice
        self._external_llm_allowed = list(external_llm_allowed)
        self._user_output_max = user_output_max

    def can_send_to_external_llm(self, payload_label: Label) -> FlowDecision:
        for allowed in self._external_llm_allowed:
            if self._lattice.can_flow(payload_label, allowed):
                return FlowDecision(True, "Allowed by external LLM policy.")
        return FlowDecision(
            False,
            f"Label {payload_label} exceeds external LLM policy.",
        )

    def can_send_to_user(self, payload_label: Label) -> FlowDecision:
        if self._lattice.can_flow(payload_label, self._user_output_max):
            return FlowDecision(True, "Allowed by user output policy.")
        return FlowDecision(False, f"Label {payload_label} exceeds user clearance.")

