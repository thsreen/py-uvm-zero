"""Test fixture: a sequence that publishes through a spanning monitor."""
from uvm_zero_base import Stimulus, Transaction


class TopSpanPublishes(Stimulus):
    async def run(self):
        self.parent.monitors["monitor"].publish(Transaction("span"))
