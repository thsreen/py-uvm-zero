"""Test fixture: a sequence that sends to a spanning and a child driver."""
from uvm_zero_base import Stimulus, Transaction


class TopSpanSends(Stimulus):
    async def run(self):
        await self.send(Transaction("span"), driver="driver")
        await self.send(Transaction("child"), driver="left.driver")
