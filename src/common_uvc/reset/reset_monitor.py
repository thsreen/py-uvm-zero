"""Reset UVC monitor: watches reset toggles and resets the agent that owns it."""
from cocotb.triggers import Event, ReadOnly, Timer, ValueChange
from cocotb.utils import get_sim_time
from uvm_zero_base import Monitor, Transaction

_TOLERANCE_NS = 1e-6


class ResetMonitor(Monitor):
    """Check reset when it toggles, and reset the agent that owns this reset UVC.

    Each pulse must last min_duration_ns.
    """

    def __init__(self, name, parent=None, *, reset_signal="reset", active_high=True,
                 min_duration_ns=20, reset_parent=True, **kwargs):
        super().__init__(name, parent, **kwargs)
        self.reset_signal = reset_signal
        self.active_high = active_high
        self.min_duration_ns = min_duration_ns
        self.reset_parent = reset_parent
        self.pulse_durations_ns = []
        self.released = Event()
        self._asserted = False
        self._asserted_at_ns = None

    async def run(self):
        reset = getattr(self.interface, self.reset_signal)
        await ReadOnly()
        self._observe_initial(reset)
        if self._asserted and self.reset_parent:
            # Hierarchy reactions may write signals, which ReadOnly forbids.
            await Timer(1, unit="step")
            self.parent.parent.apply_reset()

        while True:
            # Not ReadOnly: code woken by released must still be able to drive signals.
            await ValueChange(reset)
            self._observe(reset)

    def _observe_initial(self, reset):
        """A pulse already in progress after time zero has an unknown start."""
        if reset.value.is_resolvable and int(reset.value) == int(self.active_high):
            self._asserted = True
            now = get_sim_time(unit="ns")
            self._asserted_at_ns = now if now == 0 else None
            self.publish(Transaction({"asserted": True, "time_ns": now}))

    def _observe(self, reset):
        if not reset.value.is_resolvable:
            if self._asserted:
                self.error("Reset became unresolved during a pulse")
            return

        now = get_sim_time(unit="ns")
        asserted = int(reset.value) == int(self.active_high)
        if asserted and not self._asserted:
            self._asserted = True
            self._asserted_at_ns = now
            self.released.clear()
            if self.reset_parent:
                self.parent.parent.apply_reset()
            self.publish(Transaction({"asserted": True, "time_ns": now}))
        elif not asserted and self._asserted:
            self._end_pulse(now)

    def _end_pulse(self, now):
        started = self._asserted_at_ns
        self._asserted = False
        self._asserted_at_ns = None
        self.released.set()
        if self.reset_parent:
            self.parent.parent.release_reset()
        duration = None if started is None else now - started
        if duration is not None:
            self.pulse_durations_ns.append(duration)

        self.publish(Transaction({"asserted": False, "time_ns": now, "duration_ns": duration}))
        if duration is not None and duration < self.min_duration_ns - _TOLERANCE_NS:
            self.error(f"Reset lasted {duration} ns; expected at least {self.min_duration_ns} ns")
