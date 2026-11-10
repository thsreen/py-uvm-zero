"""Test fixture: a child agent's driver below a spanning driver."""
from uvm_zero_base import Driver


class TopLeftSpanChildDriver(Driver):
    driven = []

    async def drive(self, item):
        TopLeftSpanChildDriver.driven.append(item.data)
