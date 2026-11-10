"""Monitor: keeps interface observations current and publishes protocol items."""
from functools import partial

from cocotb.handle import ArrayObject
from cocotb.triggers import First, ReadOnly, ValueChange

from .component import BoundComponent


class Monitor(BoundComponent):
    """Observe signals in run(); publish transactions on named interface channels.

    Background sampling keeps each interface handler current even between protocol
    transfers. Sampling does not emit callbacks or keep the heartbeat alive.
    """

    def __init__(self, name, parent=None, *, interface=None, interfaces=None):
        super().__init__(name, parent, interface=interface, interfaces=interfaces)
        self._last_published = {}
        self._interface_callbacks = {}

    def add_callback(self, callback, *, interface=None):
        """Subscribe to one interface, or to every published item if omitted."""
        if interface is None:
            super().add_callback(callback)
        else:
            self._select_interface(interface)
            self._interface_callbacks.setdefault(self._interface_key(interface), []).append(callback)

    def _interface_key(self, interface):
        if not self.interfaces and interface is None:
            return None

        selected = self._select_interface(interface)
        if isinstance(interface, str):
            return interface

        names = [name for name, bound in self.interfaces.items() if bound is selected]
        if len(names) != 1:
            raise ValueError(f"{self.path}: select an interface by name from {names}")

        return names[0]

    def observe(self, interface=None):
        """Refresh the interface's observed values, without publishing or heartbeat."""
        selected = self.interfaces.values() if interface is None else [self._select_interface(interface)]
        for bound in selected:
            bound._sample()

    def publish(self, transaction, *, interface=None):
        """Update the selected handler first, then deliver one protocol transaction.

        With several interfaces the caller must select the originating interface.
        Repeated transactions are delivered; handshake traffic may repeat values.
        """
        key = self._interface_key(interface)
        self.observe(key)
        if transaction.source is None:
            transaction.source = self.path

        self._last_published[key] = transaction
        for callback in tuple(self._interface_callbacks.get(key, ())):
            callback(transaction)
        self.trigger_callbacks(transaction)

    def publish_changed(self, transaction, *, interface=None):
        """Update observations always, but publish only changed protocol items."""
        key = self._interface_key(interface)
        if key not in self._last_published or transaction != self._last_published[key]:
            self.publish(transaction, interface=key)  # publish() samples the interface itself
        else:
            self.observe(key)

    async def _run_body(self):
        for interface in set(self.interfaces.values()):
            if interface._observer is None or interface._observer.done():
                # Share one observer even when several monitors use this interface.
                # It lives for the test, including agent reset intervals.
                interface._observer = self.root.spawn(partial(self._watch_values, interface))

        await self.run()

    @staticmethod
    def _leaves(signal):
        if isinstance(signal, ArrayObject):
            for child in signal:
                yield from Monitor._leaves(child)
        elif not signal.is_const:
            yield signal

    async def _watch_values(self, interface):
        # Clocks toggle every cycle and are not tracked in values; watching them would wake every edge.
        signals = {signal for name, root in interface.signals.items() if name not in interface.clocks
                   for signal in self._leaves(root)}
        while True:
            await ReadOnly()
            interface._sample()
            if not signals:
                return

            changes = [ValueChange(signal) for signal in signals]
            await (changes[0] if len(changes) == 1 else First(*changes))

    async def run(self):
        """Override to decode transfers and call the interface's publish method."""
