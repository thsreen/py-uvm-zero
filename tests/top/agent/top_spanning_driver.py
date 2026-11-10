"""Test fixture: a driver that spans its child agents' interfaces."""
from uvm_zero_base import Driver


class TopSpanningDriver(Driver):
    driven = []

    async def drive(self, item):
        TopSpanningDriver.driven.append(sorted(self.interfaces))
