"""Reset UVC agent: active drives reset, passive watches it and resets its parent agent."""
from functools import partial

from uvm_zero_base import Agent, Transaction
from .reset_driver import ResetDriver
from .reset_monitor import ResetMonitor
from .reset_handler import ResetHandler


class ResetAgent(Agent):
    """Active: drive and observe reset. Passive: observe and reset the parent.

    A passive agent checks the minimum pulse width whenever reset toggles, and
    resets the agent that contains it. Only the top-level one should be active.
    An active agent's handler publishes reset_state for sequences to consume.
    """

    resettable = False
    forward_monitors = False
    handler_type = ResetHandler

    def __init__(self, name, parent=None, *, active=True, reset_signal="reset", period_ns=10,
                 duration_factor=2, active_high=True, **kwargs):
        settings = {"reset_signal": reset_signal, "active_high": active_high}
        if active:
            kwargs["driver_types"] = {"driver": partial(
                ResetDriver, period_ns=period_ns, duration_factor=duration_factor, **settings)}

        kwargs["monitor_types"] = {"monitor": partial(
            ResetMonitor, min_duration_ns=0 if active else period_ns * duration_factor,
            reset_parent=not active, **settings)}

        self.duration_factor = duration_factor
        super().__init__(name, parent, active, **kwargs)

    def connect_callbacks(self):
        self.monitors["monitor"].add_callback(self.handler.observe_reset)

    async def wait_released(self):
        """Return once the current or first reset pulse has been released."""
        if self.handler is not None:
            await self.handler.wait_released()
        else:
            await self.monitors["monitor"].released.wait()

    def pulse(self, duration_factor=None):
        """Request another reset pulse; active agents only. Await the result for its release.

        The pulse is queued before this returns, so wait_released() called right after
        cocotb.start_soon(reset.pulse()) waits for this pulse, not an earlier one.
        """
        self.handler.queue(Transaction(duration_factor or self.duration_factor), driver="driver")
        return self.handler.wait_released()
