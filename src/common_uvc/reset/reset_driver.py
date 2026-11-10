"""Reset UVC driver: applies reset pulses; the monitor records observed state."""
from cocotb.triggers import FallingEdge, Timer
from uvm_zero_base import Driver, Transaction
from .reset_handler import ResetState


class ResetDriver(Driver):
    """Drive one reset pulse at startup, and any others that are requested.

    The registered ResetHandler's reset_state follows each pulse. Set
    release_clock to a clock handle to delay release to its next falling edge,
    which avoids racing the rising edge at the end of the pulse.
    """

    def __init__(self, name, parent=None, *, reset_signal="reset", active_high=True,
                 period_ns=10, duration_factor=2, release_clock=None, **kwargs):
        super().__init__(name, parent, **kwargs)
        self.reset_signal = reset_signal
        self.active_high = active_high
        self.period_ns = period_ns
        self.duration_factor = duration_factor
        self.release_clock = release_clock

    async def run(self):
        await self.send(Transaction(self.duration_factor))
        await super().run()

    async def drive(self, item):
        self.drive_values(**{self.reset_signal: int(self.active_high)})
        await Timer(self.period_ns * item.data, unit="ns")
        if self.release_clock is not None:
            await FallingEdge(self.release_clock)

        self.drive_values(**{self.reset_signal: int(not self.active_high)})
        await self.handler.wait_state(ResetState.ResetInactive)
