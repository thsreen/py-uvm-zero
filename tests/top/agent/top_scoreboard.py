"""Test fixture: a named class, so connections can refer to it."""
from uvm_zero_base import Scoreboard


class TopScoreboard(Scoreboard):
    def on_monitor_callback(self, transaction):
        pass  # the base callback wrapper records it
