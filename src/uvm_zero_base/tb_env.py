"""TbEnv: the testbench root; runs the lifecycle, watchdogs, drain, and error limit."""
from asyncio import CancelledError
import logging
import os

import cocotb
from cocotb.triggers import ClockCycles, Event, First, NullTrigger, ReadOnly, Timer, current_gpi_trigger, select

from .agent import Agent
from .component import Component
from .scoreboard import Scoreboard
from .stimulus import Stimulus
from .handler import Handler
from .settings import ENV_DEFAULTS, SCOREBOARD_DEFAULTS, resolve


_UNSET = object()


class TbEnv(Component):
    """The root of a testbench: owns the run, its error limit, and its watchdogs.

    Concrete environments construct their UVCs and bind interfaces in __init__.
    The common test supplies sequence_type and sequence_config from the Makefile.
    The run has a simulation-time watchdog, defaulting to 1 ms; set timeout to
    None to disable it. Scoreboard callbacks feed one shared heartbeat. When the
    stimulus ends, driver queues drain and monitors get a quiet sampling window.
    Protocol completion checks belong in the extended scoreboards.
    """

    # Resets act on agents; the top-level sequence orchestrates and survives them.
    resettable = False
    sequence_type = None
    # Optional factory (name, parent) giving each JSON-built agent its reset UVC.
    agent_reset_type = None

    def __init__(self, name, dut, *, sequence_type=None, sequence_config=None, tb_config=None, test=None,
                 heartbeat_clock=None, max_errors=_UNSET, timeout=_UNSET, timeout_unit=_UNSET,
                 heartbeat_timeout=_UNSET, drain_cycles=_UNSET, scoreboard=None, clock=None, reset=None):
        """Settings resolve in three layers, later winning: Python defaults (settings.py),
        TB_CONFIG "settings", then arguments given here (TB_ENV_CONFIG passes them).
        scoreboard, clock, and reset are dictionaries overriding those TB_CONFIG sections.

        The top stimulus is sequence_type, created here, or for a TB_CONFIG the
        registered stimulus a test names in simulation.tests: test, or the first."""
        super().__init__(name)
        # Component loggers sit under this root's path; show their info() at
        # cocotb's log level (COCOTB_LOG_LEVEL, default INFO), not Python's WARNING.
        try:
            logging.getLogger(self.path).setLevel(os.environ.get("COCOTB_LOG_LEVEL", "INFO").upper())
        except ValueError:
            logging.getLogger(self.path).setLevel(logging.INFO)

        plan = None
        if tb_config is not None:
            # The builder is separate tooling, loaded only for a TB_CONFIG testbench.
            from uvm_zero_builder.plan import load_plan

            plan = load_plan(tb_config, clock=clock, reset=reset)
        elif clock or reset:
            raise ValueError("clock and reset settings need a TB_CONFIG")

        from_json = dict(plan.settings) if plan is not None else {}
        json_scoreboard = from_json.pop("scoreboard", None)
        given = {key: value for key, value in (
            ("max_errors", max_errors), ("timeout", timeout), ("timeout_unit", timeout_unit),
            ("heartbeat_timeout", heartbeat_timeout), ("drain_cycles", drain_cycles)) if value is not _UNSET}
        settings = resolve(ENV_DEFAULTS, from_json, given)
        # Every scoreboard under this env takes these as its defaults.
        self.scoreboard_settings = resolve(SCOREBOARD_DEFAULTS, json_scoreboard, scoreboard, where="scoreboard")

        self.dut = dut
        self.max_errors = settings["max_errors"]
        self.errors = []
        self._failure_event = Event()
        self._run_failure = None
        # The top agent's reset handler: the sequence waits for its first release, and
        # restarts after each reset if the handler's restart_sequence is set.
        self.reset_handler = None

        self.timeout = settings["timeout"]
        self.timeout_unit = settings["timeout_unit"]

        self.heartbeat_clock = heartbeat_clock
        self.heartbeat_timeout = settings["heartbeat_timeout"]
        self.drain_cycles = settings["drain_cycles"]
        self._heartbeat_event = Event()
        self._activity = 0
        selected = sequence_type or self.sequence_type
        if selected is not None and test is not None:
            raise ValueError("choose either sequence_type or a test from simulation.tests, not both")

        self.test = None
        self.stimulus = self._create_sequence(selected, sequence_config)
        if plan is not None:
            from uvm_zero_builder.build import build_testbench

            build_testbench(self, plan)
            if selected is None:
                self.stimulus = self._test_stimulus(plan.simulation["tests"], test, sequence_config)
        elif test is not None:
            raise ValueError(f"test {test!r} needs a TB_CONFIG with simulation.tests")
        elif sequence_config and selected is None:
            raise ValueError("sequence_config was supplied without a sequence")

    @property
    def agents(self):
        """Top-level agents by name, however they were created."""
        return {child.name: child for child in self.children if isinstance(child, Agent)}

    def _create_sequence(self, sequence_type, sequence_config):
        """Create the selected scenario; run() awaits it."""
        if sequence_type is None:
            return None

        return sequence_type("stimulus", self, **dict(sequence_config or {}))

    def _test_stimulus(self, tests, test, settings):
        """The registered stimulus a test names; settings override its attributes."""
        if not tests:
            if test is not None or settings:
                raise ValueError("the TB_CONFIG has no simulation.tests to run")
            return None

        name = test if test is not None else next(iter(tests))
        if name not in tests:
            raise ValueError(f"unknown test {name!r}; simulation.tests defines {sorted(tests)}")

        # The config check guarantees one instance of each test's stimulus class.
        stimulus = next(node for node in self.walk()
                        if isinstance(node, Stimulus) and type(node).__name__ == tests[name])
        for key, value in dict(settings or {}).items():
            if not hasattr(stimulus, key):
                raise ValueError(f"{stimulus.path}: no setting {key!r}; give it a default in __init__")
            setattr(stimulus, key, value)

        self.test = name
        return stimulus

    async def run(self):
        """Run the test's stimulus, which coordinates nested scenarios.

        The env owns this run, so a reset of the stimulus's agent never stops it,
        even when the stimulus applies that reset itself. Only the reset handler's
        restart_sequence restarts it, from the top, after each reset.
        """
        stimulus = self.stimulus
        if stimulus is None:
            raise NotImplementedError("Name a test in TB_CONFIG simulation.tests, pass sequence_type, "
                                      "or implement run()")

        while True:
            watcher = None
            if self.reset_handler is not None:
                await self.reset_handler.wait_released()

            body = cocotb.start_soon(stimulus.run())
            if self.reset_handler is not None:
                watcher = self.spawn(self._restart_on_reset(stimulus, body))

            try:
                await body
            except CancelledError:
                if not body.cancelled():
                    raise
                continue  # A reset with restart_sequence set: run it again.
            finally:
                if watcher is not None:
                    watcher.cancel()

            return

    async def _restart_on_reset(self, stimulus, body):
        """Cancel the run, and its nested scenarios, at the first reset that asks for a restart."""
        while True:
            await self.reset_handler.wait_asserted()
            if self.reset_handler.restart_sequence:
                for node in stimulus.walk():
                    node._kill_tasks()
                body.cancel()
                return

            await self.reset_handler.wait_released()

    def _run_body(self):
        return self._run_and_drain()

    async def _run_and_drain(self):
        await self.run()
        await self._drain()

    async def _drain(self):
        """Wait until handlers empty and scoreboards stay quiet for drain_cycles.

        Runs inside the watchdog and heartbeat, so a hung transaction still fails.
        """
        scoreboards = [node for node in self.walk() if isinstance(node, Scoreboard)]
        waiting = [node for node in self.walk() if isinstance(node, Handler)]
        while True:
            activity = self._activity
            for item in waiting:
                await item.wait_idle()

            # Leave time for a monitor to observe items still reaching it.
            if scoreboards and self.drain_cycles:
                await ClockCycles(self.heartbeat_clock, self.drain_cycles)

            # Let every monitor sample this timestep, including ReadOnly callbacks,
            # before checking activity. Return to a writable phase for cleanup.
            if not isinstance(current_gpi_trigger(), ReadOnly):
                await ReadOnly()
            await Timer(1, unit="step")

            if activity == self._activity and all(item.idle for item in waiting):
                return

    def record_failure(self, error):
        """End the run with the first failure from any component task."""
        if self._run_failure is None:
            self._run_failure = error

        self._failure_event.set()

    def report_phase(self):
        self.info(f"Simulation summary: {self.error_count} error(s)")
        for path, message in self.errors:
            self.info(f"{path}: {message}")

    def note_activity(self):
        """Record scoreboard callback activity and restart the shared heartbeat."""
        self._activity += 1
        self._heartbeat_event.set()

    async def _wait_for_run(self, body):
        """Bound the whole run in simulation time, independently of clock activity."""
        triggers = [body, self._failure_event.wait()]
        watchdog = None
        if self.timeout is not None:
            watchdog = Timer(self.timeout, unit=self.timeout_unit)
            triggers.append(watchdog)

        # select() leaves the run task running; it is stopped with the other tasks.
        first, _ = await select(*triggers)
        if self._run_failure is not None:
            raise self._run_failure

        if watchdog is not None and first == len(triggers) - 1:
            busy = [node.path for node in self.walk()
                    if isinstance(node, Handler) and not node.idle]
            message = f"Global watchdog timeout after {self.timeout} {self.timeout_unit}"
            if busy:
                message += f"; still busy: {', '.join(busy)}"
            self.error(message)
            # A global deadline always ends the run, even below the error limit.
            raise AssertionError(message)

    def _start_heartbeat(self):
        """Start one shared checker when this hierarchy contains scoreboards."""
        if not any(isinstance(node, Scoreboard) for node in self.walk()):
            return None

        if self.heartbeat_clock is None and self.drain_cycles:
            raise ValueError(f"{self.path}: scoreboards need heartbeat_clock, or drain_cycles=0")

        if self.heartbeat_clock is None or self.heartbeat_timeout is None:
            return None

        return cocotb.start_soon(self._guard_run(self._watch_heartbeat))

    async def _watch_heartbeat(self):
        """Any scoreboard activity restarts the single testbench idle window."""
        while True:
            self._heartbeat_event.clear()
            await First(
                self._heartbeat_event.wait(),
                ClockCycles(self.heartbeat_clock, self.heartbeat_timeout),
            )
            if self._heartbeat_event.is_set():
                continue

            # Allow callbacks at the deadline edge to emit their activity first.
            await ReadOnly()
            if self._heartbeat_event.is_set():
                continue

            self.error(f"Heartbeat timeout: no scoreboard callback activity for {self.heartbeat_timeout} cycles")

    def _stop_tasks(self, helpers):
        for task in helpers:
            task.cancel()

        self.stop()

    def _finish(self, failures):
        """Run all post-run phases even after an error, keeping the first failure."""
        for phase in ("extract_phase", "check_phase", "report_phase", "final_phase"):
            self._phase(phase, failures)

    async def run_test(self):
        """Configure, connect, run, drain, check, and summarize this hierarchy."""
        helpers = []
        failures = []

        try:
            self._phase("configure")
            self._phase("connect")
            self.start()
            body = self._task
            task = self._start_heartbeat()
            if task is not None:
                helpers.append(task)
            await self._wait_for_run(body)
        except Exception as error:
            failures.append(error)
        except BaseException:
            # The test itself is being torn down: no further await is allowed.
            self._stop_tasks(helpers)
            self._finish(failures)
            raise

        if isinstance(current_gpi_trigger(), ReadOnly):
            await Timer(1, unit="step")
        self._stop_tasks(helpers)
        # Cancellation finishes on the next scheduler step. Without this yield the
        # test could end first, and cocotb would fail it for a half-cancelled task.
        await NullTrigger()
        self._finish(failures)

        if self._run_failure is not None and not failures:
            failures.append(self._run_failure)

        if self.error_count and not failures:
            failures.append(AssertionError(f"{self.error_count} error(s) reported"))

        if failures:
            for error in failures[1:]:
                self.logger.error("Additional failure: %s", error)

            raise failures[0]
