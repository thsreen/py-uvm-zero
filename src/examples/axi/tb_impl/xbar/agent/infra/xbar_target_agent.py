"""XbarTargetAgent: construction and wiring for xbar.target.

Generated from tb.json. This is ordinary editable Python.
The generator preserves it unless --refresh-infra is explicitly requested.
"""
from pathlib import Path

from uvm_zero_base import Agent, Interface
from xbar.agent.xbar_target_resp_driver import XbarTargetRespDriver


class XbarTargetAgent(Agent):
    """Construct components here; connect their callbacks in connect_callbacks()."""

    def __init__(self, name, parent, *, config_dir=None, connected_module=None):
        config_dir = Path(config_dir) if config_dir is not None else Path(__file__).resolve().parents[3]
        connected_module = connected_module or 'dut'
        interfaces = {
            'req': Interface.from_json(parent.root.dut, config_dir / 'interfaces/target_req.json',
                                      connected_module=connected_module),
            'resp': Interface.from_json(parent.root.dut, config_dir / 'interfaces/target_resp.json',
                                      connected_module=connected_module),
        }

        super().__init__(
            name, parent,
            active=True, interfaces=interfaces,
            driver_types={'resp_driver': XbarTargetRespDriver},
            monitor_types={},
            scoreboard_types={},
            stimulus_types={},
        )
        self.connected_module = connected_module

        self.drivers['resp_driver'].interfaces = {
            'resp': self.interfaces['resp'],
        }

    def connect_callbacks(self):
        """Connections from the JSON: each source publishes to the target's on_<source>_callback."""
        # No connections: add "<SourceClass> -> <TargetClass>" entries to the JSON.
