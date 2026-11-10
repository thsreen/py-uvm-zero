"""XbarAgent: construction and wiring for xbar.

Generated from tb.json. This is ordinary editable Python.
The generator preserves it unless --refresh-infra is explicitly requested.
"""
from pathlib import Path

from uvm_zero_base import Agent
from xbar.seqs.xbar_smoke import XbarSmoke
from xbar.agent.infra.xbar_initiator_agent import XbarInitiatorAgent
from xbar.agent.infra.xbar_target_agent import XbarTargetAgent


class XbarAgent(Agent):
    """Construct components here; connect their callbacks in connect_callbacks()."""

    def __init__(self, name, parent, *, config_dir=None, connected_module=None):
        config_dir = Path(config_dir) if config_dir is not None else Path(__file__).resolve().parents[3]
        connected_module = connected_module or 'dut'
        interfaces = {}

        super().__init__(
            name, parent,
            active=True, interfaces=interfaces,
            driver_types={},
            monitor_types={},
            scoreboard_types={},
            stimulus_types={'smoke': XbarSmoke},
        )
        self.connected_module = connected_module

        XbarInitiatorAgent('initiator', self, config_dir=config_dir,
                          connected_module=connected_module)

        XbarTargetAgent('target', self, config_dir=config_dir,
                          connected_module=connected_module)

    def connect_callbacks(self):
        """Connections from the JSON: each source publishes to the target's on_<source>_callback."""
        # No connections: add "<SourceClass> -> <TargetClass>" entries to the JSON.
