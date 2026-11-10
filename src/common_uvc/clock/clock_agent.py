"""Clock UVC agent: active generates the clock, passive can check its period."""
from functools import partial

from uvm_zero_base import Agent, Monitor
from .clock_driver import ClockDriver
from .clock_monitor import ClockMonitor


class ClockAgent(Agent):
    """Active: generate and observe a clock. Passive: observe its live values.

    check_period adds a monitor to a passive agent, and only then may check_cycles
    set how many cycles lie between checks.
    """

    resettable = False
    forward_monitors = False

    def __init__(self, name, parent=None, *, active=True, clock_signal="clk", period_ns=10,
                 check_period=False, check_cycles=None, **kwargs):
        if active and check_period:
            raise ValueError("check_period applies only to a passive ClockAgent")

        if check_cycles is not None and not check_period:
            raise ValueError("check_cycles requires check_period=True")

        settings = {"clock_signal": clock_signal, "period_ns": period_ns}
        if active:
            kwargs["driver_types"] = {"driver": partial(ClockDriver, **settings)}
        if check_period:
            if check_cycles is not None:
                settings["check_cycles"] = check_cycles
            kwargs["monitor_types"] = {"monitor": partial(ClockMonitor, **settings)}
        else:
            kwargs["monitor_types"] = {"monitor": Monitor}

        super().__init__(name, parent, active, **kwargs)
