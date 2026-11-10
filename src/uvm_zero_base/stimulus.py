"""Stimulus: a scenario component, run on demand and killable by its agent's reset."""
from .component import Component
from .driver import Driver
from .handler import Handler


class Stimulus(Component):
    """A scenario in the component hierarchy, started only by its caller.

    execute() makes the scenario killable by a reset of its agent. Children need
    unique names, so create a nested scenario once in __init__ and execute it as
    often as needed. Failures propagate to the caller. Any number of sequences,
    nested or not, can share their agent's handler and pick any of its drivers.
    Verbs: queue() adds an item and returns; send() waits until it has been driven.
    """

    _auto_start = False

    @property
    def env(self):
        return self.root

    @property
    def agent(self):
        """The nearest agent above this sequence, however deeply it is nested."""
        from .agent import Agent  # Agent builds stimuli, so it imports this module first.

        node = self.parent
        while node is not None and not isinstance(node, Agent):
            node = node.parent

        return node

    @property
    def handler(self):
        """The handler this sequence feeds: its agent's, shared with its other sequences."""
        return self.agent.handler if self.agent is not None else None

    def _base(self):
        """Driver paths start at this sequence's agent, or at the env for a top-level one."""
        return self.agent if self.agent is not None else self.root

    def _driver(self, driver):
        """Follow a path such as "aw.driver" (or "axi.aw.driver" from the top); only a driver will do."""
        node = self._base()
        for name in driver.split(".") if isinstance(driver, str) else ():
            node = next((child for child in node.children if child.name == name), None)
            if node is None:
                break

        if not isinstance(node, Driver):
            raise ValueError(f"{self.path}: {driver!r} is not a driver; "
                             f"{self._driver_paths()} are available")

        return node

    def _driver_paths(self):
        """Driver paths below the base, listed only when reporting a wrong one."""
        base = self._base()
        prefix = base.path + "."
        return sorted(node.path.removeprefix(prefix) for node in base.walk() if isinstance(node, Driver))

    async def send(self, transaction, driver):
        """Drive an item now and wait for it; driver is always named, such as "aw.driver".

        Returns True once driven, or False if a reset of the driver aborted it.
        """
        selected = self._driver(driver)
        self._record(transaction)
        return await selected.send(transaction)

    def queue(self, transaction, driver, *, delay=None, max_delay=None):
        """Queue an item for a named driver and return at once; its agent's handler holds it.

        delay or max_delay (clock cycles) make the driver wait before driving it;
        see Handler.queue.
        """
        selected = self._driver(driver)
        if selected.handler is None:
            raise ValueError(f"{self.path}: driver {driver!r} has no handler "
                             "(its agent sets handler_type = None); use send() instead")

        self._record(transaction)
        selected.handler.queue(transaction, driver=selected.name, delay=delay, max_delay=max_delay)

    def _record(self, transaction):
        """Stamp this sequence's full hierarchy path on the item, for debugging."""
        transaction.sequence = self.path
        if transaction.source is None:
            transaction.source = self.path

    async def wait_idle(self):
        """Return once every handler below the base is idle at the same moment.

        Waiting on one handler at a time could return after an earlier one was
        refilled, so check them all again after each wait.
        """
        while True:
            busy = [node for node in self._base().walk() if isinstance(node, Handler) and not node.idle]
            if not busy:
                return
            await busy[0].wait_idle()

    async def execute(self):
        """Wait for reset release and run; returns False if a reset killed it."""
        await self.wait_out_of_reset()
        return await self.run_killable(self.run())

    async def run(self):
        raise NotImplementedError("Implement Stimulus.run()")
