"""Handler: an agent's common handler, holding a queue per driver and its interfaces."""
from cocotb.queue import Queue
from cocotb.triggers import Event

from .component import Component


class Handler(Component):
    """One per agent: a queue for each of the agent's drivers, shared by its sequences.

    interfaces maps every interface of the agent and its protocol descendants
    ("ip", "aw.port"), so a sequence can read their observed values.
    """

    def __init__(self, name, parent=None):
        super().__init__(name, parent)
        self.interfaces = {}
        self.drivers = {}
        self._queues = {}
        self._busy = set()
        self._idle = Event()
        self._idle.set()

    def register_driver(self, driver):
        """Give a driver its own queue here; a driver serves exactly one handler."""
        if driver.name in self.drivers or driver.handler is not None:
            raise ValueError(f"{self.path}: driver {driver.path} is already registered")

        self.drivers[driver.name] = driver
        self._queues[driver.name] = Queue()
        driver.handler = self

    def _queue_name(self, driver):
        if not self.drivers:
            raise RuntimeError(f"{self.path}: no driver registered; "
                               "an overriding Agent.connect() must call super().connect()")

        if driver not in self.drivers:
            raise ValueError(f"{self.path}: unknown driver {driver!r}; {sorted(self.drivers)} are available")

        return driver

    def queue(self, transaction, driver, *, delay=None, max_delay=None):
        """Queue an item for the named driver and return at once; the name is always given.

        delay waits exactly that many cycles of the driver's clock before the driver
        drives the item; max_delay waits a random 0..max_delay cycles. Without either,
        the driver's own max_delay applies. Items keep their order either way.
        """
        name = self._queue_name(driver)
        for key, value in (("delay", delay), ("max_delay", max_delay)):
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{self.path}: {key} must be a non-negative number of clock cycles, got {value!r}")
        if delay is not None and max_delay is not None:
            raise ValueError(f"{self.path}: give delay or max_delay, not both")

        if transaction.source is None:
            transaction.source = self.path

        self._idle.clear()
        self._queues[name].put_nowait((transaction, delay, max_delay))

    async def pop(self, driver):
        """Driver side: wait for the next item; returns (transaction, delay, max_delay)."""
        item = await self._queues[driver].get()
        self._busy.add(driver)
        return item

    def item_done(self, driver):
        """Driver side: report that the popped item is finished."""
        self._busy.discard(driver)
        self._update_idle()

    def flush(self):
        """Discard every queued item, in every queue."""
        for queue in self._queues.values():
            while not queue.empty():
                queue.get_nowait()

        self._update_idle()

    def _update_idle(self):
        if self.idle:
            self._idle.set()

    @property
    def idle(self):
        return not self._busy and all(queue.empty() for queue in self._queues.values())

    async def wait_idle(self):
        """Return once every queued item, for every driver, has been handled."""
        if not self.idle:
            await self._idle.wait()

    def on_reset_asserted(self):
        self._busy.clear()
        self.flush()
