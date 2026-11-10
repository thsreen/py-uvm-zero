"""Driver: turns transactions into signal activity, fed by its handler or send()."""
from cocotb.handle import ArrayObject
from cocotb.triggers import ClockCycles, Lock, ReadWrite, Timer

from .component import BoundComponent


class Driver(BoundComponent):
    """Translate transaction items into signal activity on an interface.

    run() pops items from this driver's queue in its agent's handler and sends
    them. A subclass that overrides run() must await super().run() to keep serving
    its handler.
    A reset of this driver kills the item being driven and calls drive_idle().
    send() serializes whole transactions. For pipelined protocols, use one driver
    per independent channel so each channel is serialized separately.

    max_delay (default 0) is the most clock cycles to wait, at random, before
    driving each queued item; an item queued with delay or max_delay overrides it.
    Cycles count the interface clock tagged [Clock].
    """

    def __init__(self, name, parent=None, *, interface=None, interfaces=None):
        super().__init__(name, parent, interface=interface, interfaces=interfaces)
        self._send_lock = Lock()
        self.handler = None
        self._resets = 0
        self.max_delay = 0

    async def run(self):
        """Send items from the handler; a failure in drive() ends the run."""
        if self.handler is None:
            return

        while True:
            transaction, delay, max_delay = await self.handler.pop(self.name)
            cycles = self._delay_cycles(delay, max_delay)
            if cycles:
                await ClockCycles(self._clock(), cycles)
            await self._leave_read_only()
            await self.send(transaction)
            self.handler.item_done(self.name)

    def _delay_cycles(self, delay, max_delay):
        """The cycles to wait before this item: exact, or random from this driver's seeded stream."""
        if delay is not None:
            return delay

        limit = self.max_delay if max_delay is None else max_delay
        return self.random.randint(0, limit) if limit else 0

    def _clock(self):
        """The clock tagged [Clock] on this driver's interfaces; delays count its rising edges."""
        for interface in self.interfaces.values():
            if interface.clocks:
                return next(iter(interface.clocks.values()))

        raise RuntimeError(f"{self.path}: a queue delay counts clock cycles; tag the interface's clock "
                           "[Clock] in its JSON (or tags={'clk': 'Clock'} in Python)")

    @staticmethod
    async def _leave_read_only():
        """Make signal writes legal: a monitor may have queued during ReadOnly."""
        try:
            await ReadWrite()
        except RuntimeError:
            await Timer(1, unit="step")

    async def send(self, transaction):
        """Serialize requests and return once drive() has finished.

        Returns True when the item was driven, or False when a reset killed it.
        During reset, the call waits for release. Exceptions propagate to the caller.
        """
        if not self.interfaces:
            raise RuntimeError(f"{self.path}: connect an interface before sending")

        resets = self._resets
        async with self._send_lock:
            await self.wait_out_of_reset()
            if resets != self._resets:
                return False

            transaction.driver = self.path
            self.debug(f"drive {transaction!r}")
            return await self.run_killable(self.drive(transaction))

    async def drive(self, transaction):
        """Override with protocol-specific signal driving and timing."""
        raise NotImplementedError("Implement Driver.drive(transaction)")

    def drive_values(self, interface=None, **values):
        """Write changed signals only; never change the interface's observed values.

        With one bound interface, name only the signals: drive_values(valid=1).
        With several, name the interface first: drive_values("ip", valid=1).
        A single value given for an array signal is written to every element.
        Timing remains the protocol driver's responsibility. Comparing with the live
        DUT value also covers a write before the monitor's next observation.
        Returns the names actually written.
        """
        selected = self._select_interface(interface)
        unknown = values.keys() - selected.signals.keys()
        if unknown:
            raise ValueError(f"{self.path}: unknown signals {sorted(unknown)}")

        changed = []
        for name, value in values.items():
            if isinstance(selected.signals[name], ArrayObject) and not isinstance(value, (list, tuple)):
                value = [value] * len(selected.signals[name])
            if selected.current(name) != value:
                selected.signals[name].value = value
                changed.append(name)

        return tuple(changed)

    def drive_idle(self):
        """Override to set this driver's outputs to their idle values."""

    def on_reset_asserted(self):
        self._resets += 1
        # The item in flight is gone; a reset of this driver alone must not leave it busy.
        if self.handler is not None:
            self.handler.item_done(self.name)
        self.drive_idle()
