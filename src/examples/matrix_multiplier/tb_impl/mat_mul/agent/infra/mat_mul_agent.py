"""MatMulAgent: construction and wiring for mat_mul.

Generated from tb.json. This is ordinary editable Python.
The generator preserves it unless --refresh-infra is explicitly requested.
"""
from pathlib import Path

from uvm_zero_base import Agent, Interface
from mat_mul.agent.mat_mul_ip_monitor import MatMulIpMonitor
from mat_mul.agent.mat_mul_op_monitor import MatMulOpMonitor
from mat_mul.agent.mat_mul_ip_driver import MatMulIpDriver
from mat_mul.agent.mat_mul_scoreboard import MatMulScoreboard
from mat_mul.seqs.mat_mul_traffic import MatMulTraffic


class MatMulAgent(Agent):
    """Construct components here; connect their callbacks in connect_callbacks()."""

    def __init__(self, name, parent, *, config_dir=None, connected_module=None):
        config_dir = Path(config_dir) if config_dir is not None else Path(__file__).resolve().parents[3]
        connected_module = connected_module or 'dut'
        interfaces = {
            'ip': Interface.from_json(parent.root.dut, config_dir / 'interfaces/input.json',
                                      connected_module=connected_module),
            'op': Interface.from_json(parent.root.dut, config_dir / 'interfaces/output.json',
                                      connected_module=connected_module),
        }

        super().__init__(
            name, parent,
            active=True, interfaces=interfaces,
            driver_types={'ip_driver': MatMulIpDriver},
            monitor_types={'ip_monitor': MatMulIpMonitor, 'op_monitor': MatMulOpMonitor},
            scoreboard_types={'scoreboard': MatMulScoreboard},
            stimulus_types={'traffic': MatMulTraffic},
        )
        self.connected_module = connected_module

        self.drivers['ip_driver'].interfaces = {
            'ip': self.interfaces['ip'],
        }

        self.monitors['ip_monitor'].interfaces = {
            'ip': self.interfaces['ip'],
        }

        self.monitors['op_monitor'].interfaces = {
            'op': self.interfaces['op'],
        }

    def connect_callbacks(self):
        """Connections from the JSON: each source publishes to the target's on_<source>_callback."""
        # MatMulIpMonitor -> MatMulScoreboard
        self.scoreboards['scoreboard'].subscribe(
            self.monitors['ip_monitor'], self.scoreboards['scoreboard'].on_ip_monitor_callback)
        # MatMulOpMonitor -> MatMulScoreboard
        self.scoreboards['scoreboard'].subscribe(
            self.monitors['op_monitor'], self.scoreboards['scoreboard'].on_op_monitor_callback)
