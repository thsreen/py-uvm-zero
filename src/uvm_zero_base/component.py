"""Component: the hierarchy node every testbench part builds on (phases, tasks, reset, errors)."""
from asyncio import CancelledError
import logging
import random

import cocotb
from cocotb.triggers import Event



class Component:
    """A named node in a small component hierarchy.

    A reset of an agent reaches every resettable component below it: their tasks
    are killed, and their run() loops restart on release.
    """

    resettable = True

    _auto_start = True

    def __init__(self, name, parent=None):
        if not name or "." in name:
            raise ValueError("name must be nonempty and cannot contain '.'")

        self.name = name
        self.parent = parent
        self.children = []

        self._callbacks = []
        self._task = None
        self._killable = set()
        self._reset_holds = 0
        # True while an agent above (or this one) is held in reset.
        self.in_reset = False
        self._out_of_reset = Event()
        self._out_of_reset.set()
        self._random = None

        if parent is not None:
            if any(child.name == name for child in parent.children):
                raise ValueError(f"duplicate child name: {name}")

            parent.children.append(self)

    # Hierarchy and identity

    @property
    def path(self):
        return f"{self.parent.path}.{self.name}" if self.parent else self.name

    @property
    def root(self):
        return self.parent.root if self.parent else self

    @property
    def random(self):
        """A generator seeded from the test seed and this component's path."""
        if self._random is None:
            self._random = random.Random(f"{cocotb.RANDOM_SEED}:{self.path}")

        return self._random

    def walk(self):
        """Yield this component, then its descendants in hierarchy order."""
        yield self
        for child in self.children:
            yield from child.walk()

    # Lifecycle hooks, in execution order

    def configure(self):
        """Set component and interface configuration before connections exist."""

    def connect(self):
        """Connect this component's callbacks after construction of the hierarchy."""

    async def run(self):
        """Override to implement concurrent component behavior."""

    def extract_phase(self):
        """Collect final state and statistics after run tasks stop."""

    def check_phase(self):
        """Check this component's final results; do not traverse children."""

    def report_phase(self):
        """Report results after checks, including post-error context."""

    def final_phase(self):
        """Release resources after all reporting is complete."""

    # Reset notifications, delivered across the hierarchy by TbEnv

    def on_reset_asserted(self):
        """Override to react when reset asserts."""

    def on_reset_released(self):
        """Override to react when reset is released."""

    def apply_reset(self):
        """Reset this subtree: kill its tasks, then call on_reset_asserted()."""
        for node in self._reset_nodes():
            node._reset_holds += 1
            if node._reset_holds == 1:
                node.in_reset = True
                node._out_of_reset.clear()
                node._kill_tasks()
                node.on_reset_asserted()

    def release_reset(self):
        """Release this subtree and restart its run() loops."""
        for node in self._reset_nodes():
            if node._reset_holds == 0:
                continue

            node._reset_holds -= 1
            if node._reset_holds == 0:
                node.on_reset_released()
                node.in_reset = False
                node._out_of_reset.set()
                node._start_run()

    async def wait_out_of_reset(self):
        """Return once this component is out of reset; at once if it already is."""
        await self._out_of_reset.wait()

    def _reset_nodes(self):
        """Yield parents before children, so a killed caller stops before its callee."""
        if self.resettable:
            yield self
            for child in self.children:
                yield from child._reset_nodes()

    def _kill_tasks(self):
        if self._task is not None:
            self._task.cancel()
            self._task = None

        tasks, self._killable = self._killable, set()
        for task in tasks:
            task.cancel()

    # Phase dispatch

    def _phase(self, name, failures=None):
        """Dispatch one synchronous phase across the subtree exactly once."""
        parent_first = name in ("configure", "final_phase")
        if parent_first:
            self._invoke_phase(name, failures)

        for child in self.children:
            child._phase(name, failures)

        if not parent_first:
            self._invoke_phase(name, failures)

    def _invoke_phase(self, name, failures):
        """Call a local hook, optionally collecting failures for later reporting."""
        self.debug(f"{name}: {self.path}")
        try:
            old = name.removesuffix("_phase")
            if old != name and callable(getattr(type(self), old, None)):
                # The hook was renamed; an old method would otherwise be skipped silently.
                raise TypeError(f"{type(self).__name__}.{old}(): rename it to {name}()")
            getattr(self, name)()
        except Exception as error:
            if failures is None:
                raise

            self.logger.error("%s failed: %s", name, error)
            failures.append(error)

    # Concurrent task control

    def start(self):
        """Schedule this subtree's run() overrides."""
        for component in self.walk():
            component._start_run()

    def _start_run(self):
        # A component held in reset starts when the reset is released.
        if self._auto_start and not self._reset_holds and type(self).run is not Component.run:
            self._task = cocotb.start_soon(self._guard_run(self._run_body))

    def _run_body(self):
        return self.run()

    def stop(self):
        """Cancel any running tasks in this subtree."""
        for component in self.walk():
            component._kill_tasks()

    def spawn(self, coroutine):
        """Start a background task that a reset of this component kills."""
        self._killable = {task for task in self._killable if not task.done()}
        task = cocotb.start_soon(self._guard_run(coroutine))
        self._killable.add(task)
        return task

    async def run_killable(self, coroutine):
        """Await a coroutine; returns False if a reset of this component killed it."""
        task = cocotb.start_soon(coroutine)
        self._killable.add(task)
        try:
            await task
        except CancelledError:
            if not task.cancelled():
                raise

            return False
        finally:
            if task in self._killable:
                self._killable.discard(task)
                task.cancel()

        return True

    async def _guard_run(self, coroutine):
        """Forward background failures to the root's running test lifecycle."""
        try:
            await (coroutine() if callable(coroutine) else coroutine)
        except Exception as error:
            self.root.record_failure(error)

    # Transaction callbacks

    def add_callback(self, callback):
        self._callbacks.append(callback)

    def trigger_callbacks(self, *args, **kwargs):
        for callback in tuple(self._callbacks):
            callback(*args, **kwargs)

    def publish(self, transaction):
        """Deliver an item to every connected component, such as a scoreboard
        forwarding a result to another scoreboard or to a stimulus."""
        self.trigger_callbacks(transaction)

    # Logging and error accounting

    @property
    def logger(self):
        return logging.getLogger(self.path)

    @property
    def error_count(self):
        return len(self.root.errors)

    def debug(self, message):
        self.logger.debug(message)

    def info(self, message):
        self.logger.info(message)

    def warn(self, message):
        self.logger.warning(message)

    def error(self, message):
        """Record a failure; raises AssertionError once the root's limit is reached."""
        root = self.root
        root.errors.append((self.path, str(message)))
        self.logger.error(message)

        if root.error_count >= root.max_errors:
            raise AssertionError(
                f"{self.path}: error limit reached "
                f"({root.error_count} of {root.max_errors}): {message}"
            )


class BoundComponent(Component):
    """A component that needs DUT interfaces: the shared base of Driver and Monitor."""

    def __init__(self, name, parent=None, *, interface=None, interfaces=None):
        super().__init__(name, parent)

        from .interface import Interface

        self.interfaces = Interface.collect(interface, interfaces)

    @property
    def interface(self):
        """The bound interface; None when there are zero or several."""
        return next(iter(self.interfaces.values())) if len(self.interfaces) == 1 else None

    def bind_interface(self, interface):
        """Bind this component directly to an Interface instance."""
        self.interfaces = {"default": interface}

    def _select_interface(self, interface=None):
        from .interface import Interface

        if interface is None and self.interface is not None:
            return self.interface
        if isinstance(interface, str) and interface in self.interfaces:
            return self.interfaces[interface]
        if isinstance(interface, Interface) and interface in self.interfaces.values():
            return interface

        raise ValueError(f"{self.path}: select a bound interface from {sorted(self.interfaces)}")

    def connect(self):
        """Keep explicit bindings; otherwise inherit the parent's single interface."""
        if not self.interfaces:
            inherited = getattr(self.parent, "interfaces", {})
            if len(inherited) > 1:
                raise ValueError(f"{self.path}: use bind_interface(interface) when the parent "
                                 "has multiple interfaces")

            self.interfaces = dict(inherited)

        if not self.interfaces:
            raise ValueError(f"{self.path}: requires an interface")
