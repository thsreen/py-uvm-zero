"""XbarInitiatorAgent: construction and wiring for xbar.initiator.

Generated from tb.json. This is ordinary editable Python.
The generator preserves it unless --refresh-infra is explicitly requested.
"""
from pathlib import Path

from uvm_zero_base import Agent, Interface
from xbar.agent.xbar_initiator_req_driver import XbarInitiatorReqDriver


class XbarInitiatorAgent(Agent):
    """Construct components here; connect their callbacks in connect_callbacks()."""

    def __init__(self, name, parent, *, config_dir=None, connected_module=None):
        config_dir = Path(config_dir) if config_dir is not None else Path(__file__).resolve().parents[3]
        connected_module = connected_module or 'dut'
        interfaces = {
            'req': Interface.from_json(parent.root.dut, config_dir / 'interfaces/initiator_req.json',
                                      connected_module=connected_module),
            'resp': Interface.from_json(parent.root.dut, config_dir / 'interfaces/initiator_resp.json',
                                      connected_module=connected_module),
        }

        super().__init__(
            name, parent,
            active=True, interfaces=interfaces,
            driver_types={'req_driver': XbarInitiatorReqDriver},
            monitor_types={},
            scoreboard_types={},
            stimulus_types={},
        )
        self.connected_module = connected_module

        self.drivers['req_driver'].interfaces = {
            'req': self.interfaces['req'],
        }

    def connect_callbacks(self):
        """Connections from the JSON: each source publishes to the target's on_<source>_callback."""
        # No connections: add "<SourceClass> -> <TargetClass>" entries to the JSON.
