"""Clock UVC driver: drives a free-running clock."""
from cocotb.clock import Clock
from cocotb.triggers import Event
from uvm_zero_base import Driver


class ClockDriver(Driver):
    def __init__(self, name, parent=None, *, clock_signal="clk", period_ns=10, **kwargs):
        super().__init__(name, parent, **kwargs)
        self.clock_signal = clock_signal
        self.period_ns = period_ns

    async def run(self):
        clock = Clock(getattr(self.interface, self.clock_signal), self.period_ns, unit="ns")
        clock.start(start_high=False)
        try:
            await Event().wait()
        finally:
            clock.stop()
