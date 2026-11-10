"""Test fixture: a named class, so connections can refer to it."""
from uvm_zero_base import Scoreboard


class AgentScoreboard(Scoreboard):
    def on_a_monitor_callback(self, transaction):
        pass  # the base callback wrapper records it

    def on_b_monitor_callback(self, transaction):
        pass  # the base callback wrapper records it
