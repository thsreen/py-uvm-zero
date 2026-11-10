"""Clock UVC monitor: an optional period check for a passive clock agent."""
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_steps, get_sim_time
from uvm_zero_base import Monitor, Transaction


class ClockMonitor(Monitor):
    """Check a clock's average period once per check_cycles cycles.

    Timing uses integer simulator steps.
    """

    def __init__(self, name, parent=None, *, clock_signal="clk", period_ns=10,
                 check_cycles=500, **kwargs):
        super().__init__(name, parent, **kwargs)
        self.clock_signal = clock_signal
        self.period_ns = period_ns
        self.check_cycles = check_cycles
        self.windows = 0

    async def run(self):
        clock = getattr(self.interface, self.clock_signal)
        expected = get_sim_steps(self.period_ns, "ns") * self.check_cycles
        await RisingEdge(clock)
        start = int(get_sim_time(unit="step"))
        while True:
            await ClockCycles(clock, self.check_cycles)
            now = int(get_sim_time(unit="step"))
            elapsed, start = now - start, now
            self.windows += 1
            if elapsed != expected:
                self.error(f"Clock period wrong: {self.check_cycles} cycles took {elapsed} steps; "
                           f"expected {expected}")
            self.publish_changed(Transaction({"window_steps": elapsed}))

    def check_phase(self):
        if not self.windows:
            self.warn(f"Clock period not checked: the run ended within {self.check_cycles} cycles")
