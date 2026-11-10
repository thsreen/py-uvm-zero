"""Self-tests: Run lifecycle, watchdog, errors, and heartbeat."""
import cocotb

from support import *  # noqa: F401,F403  shared helpers and fixtures


@cocotb.test()
async def heartbeat_does_not_break_a_passing_test(dut):
    # Passing depends on what happens after run_test(), so nothing may follow it.
    start_clock(dut)
    await scoreboard_env(dut).run_test()


@cocotb.test()
async def base_env_can_be_selected(dut):
    env = TestConfig(TbEnv, "tb", {"sequence_type": Quick}).create_env(dut)
    assert await failure_of(env) is None


@cocotb.test()
async def failing_child_sequence_reaches_its_caller(dut):
    class Bad(Stimulus):
        async def run(self):
            raise ValueError("boom")

    caught = []

    class Outer(Stimulus):
        def __init__(self, name, parent=None):
            super().__init__(name, parent)
            self.bad = Bad("bad", self)

        async def run(self):
            try:
                await self.bad.run()
            except ValueError as error:
                caught.append(str(error))
                raise

    failure = await failure_of(TbEnv("env", dut, sequence_type=Outer))
    assert caught == ["boom"]
    assert isinstance(failure, ValueError)


@cocotb.test()
async def sequences_can_run_repeatedly(dut):
    runs = []

    class One(Stimulus):
        async def run(self):
            runs.append(self.env.name)

    class Many(Stimulus):
        def __init__(self, name, parent=None):
            super().__init__(name, parent)
            self.one = One("one", self)

        async def run(self):
            for _ in range(3):
                await self.one.run()

    assert await failure_of(TbEnv("env", dut, sequence_type=Many)) is None
    assert runs == ["env"] * 3


@cocotb.test()
async def stimulus_is_a_component_that_only_runs_when_awaited(dut):
    runs = []

    class Counts(Stimulus):
        async def run(self):
            runs.append(self.path)

    class Holder(Agent):
        driver_types = {"driver": Driver}

    env = TbEnv("env", dut)
    agent = Holder("agent", env, stimulus_types={"stimulus": Counts}, interface=Interface(dut, clk="clk"))
    stimulus = agent.stimuli["stimulus"]
    assert stimulus.parent is agent and stimulus in agent.children
    env.stimulus = stimulus
    assert await failure_of(env) is None
    assert runs == ["env.agent.stimulus"]


@cocotb.test()
async def tasks_stop_before_checks(dut):
    order = []

    class Forever(TbEnv):
        pass

    from uvm_zero_base import Component

    class Worker(Component):
        async def run(self):
            try:
                await Timer(1, unit="ms")
            finally:
                order.append("task stopped")

        def check_phase(self):
            order.append("check")

    env = Forever("env", dut, sequence_type=Quick)
    Worker("worker", env)
    assert await failure_of(env) is None
    assert order == ["task stopped", "check"]


@cocotb.test()
async def watchdog_ends_the_run_below_the_error_limit(dut):
    class Long(Stimulus):
        async def run(self):
            await Timer(10, unit="us")

    failure = await failure_of(TbEnv("env", dut, sequence_type=Long, max_errors=5,
                                     timeout=1, timeout_unit="us"))
    assert isinstance(failure, AssertionError) and "watchdog" in str(failure)


@cocotb.test()
async def errors_below_the_limit_still_fail_the_test(dut):
    class Complains(Stimulus):
        async def run(self):
            self.parent.error("first")
            await Timer(1, unit="ns")

    env = TbEnv("env", dut, sequence_type=Complains, max_errors=2)
    failure = await failure_of(env)
    assert isinstance(failure, AssertionError) and env.error_count == 1


@cocotb.test()
async def max_errors_must_be_positive(dut):
    try:
        TbEnv("env", dut, max_errors=0)
    except ValueError:
        return
    raise AssertionError("max_errors=0 was accepted")


@cocotb.test()
async def heartbeat_fires_when_idle(dut):
    start_clock(dut)
    failure = await failure_of(scoreboard_env(dut, heartbeat_timeout=5))
    assert "Heartbeat timeout" in str(failure)


@cocotb.test()
async def component_info_follows_the_cocotb_log_level(dut):
    import logging

    env = TbEnv("env", dut)
    child = Component("child", env)
    expected = logging.getLevelName(os.environ.get("COCOTB_LOG_LEVEL", "INFO").upper())
    assert child.logger.getEffectiveLevel() == expected
    assert child.logger.isEnabledFor(logging.INFO) == (expected <= logging.INFO)


@cocotb.test()
async def old_phase_hooks_are_reported_not_skipped(dut):
    for old, new in (("extract", "extract_phase"), ("check", "check_phase"),
                     ("report", "report_phase"), ("final", "final_phase")):
        OldBoard = type("OldBoard", (Scoreboard,), {old: lambda self: None})
        env = TbEnv("env", dut, sequence_type=Quick, drain_cycles=0)
        OldBoard("board", env)
        error = await failure_of(env)
        assert error is not None and f"OldBoard.{old}(): rename it to {new}()" in str(error), (old, error)

