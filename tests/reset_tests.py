"""Self-tests: Clock and reset UVCs, and reset handling across agents."""
import cocotb
from cocotb.clock import Clock

from support import *  # noqa: F401,F403  shared helpers and fixtures


@cocotb.test()
async def reset_kills_the_item_being_driven_and_idles_outputs(dut):
    class Slow(Driver):
        idled = 0
        finished = []

        def drive_idle(self):
            type(self).idled += 1

        async def drive(self, item):
            await Timer(100, unit="ns")
            self.finished.append(item.data)

    results = []

    class Interrupts(Stimulus):
        async def run(self):
            await self.env.reset.wait_released()
            sender = cocotb.start_soon(self.env.a.drivers["driver"].send(Transaction(1)))
            await Timer(5, unit="ns")
            await self.env.reset.pulse(duration_factor=1)
            results.append(await sender)

    env = reset_agent_env(dut, Interrupts, Slow)
    assert await failure_of(env) is None
    assert results == [False] and Slow.finished == [] and Slow.idled == 2


@cocotb.test()
async def reset_kills_the_top_agents_stimulus(dut):
    results, finished = [], []

    class Forever(Stimulus):
        async def run(self):
            await Timer(1, unit="ms")
            finished.append(True)

    env = TbEnv("env", dut)
    agent = Agent("agent", env, stimulus_types={"stimulus": Forever})
    task = cocotb.start_soon(agent.stimuli["stimulus"].execute())
    await Timer(5, unit="ns")
    agent.apply_reset()
    results.append(await task)
    assert results == [False] and finished == []


@cocotb.test()
async def reset_kills_nested_stimulus(dut):
    results, after = [], []

    class Inner(Stimulus):
        async def run(self):
            await Timer(1, unit="ms")

    class Outer(Stimulus):
        def __init__(self, name, parent=None):
            super().__init__(name, parent)
            self.inner = Inner("inner", self)

        async def run(self):
            await self.inner.execute()
            after.append(True)

    env = TbEnv("env", dut)
    agent = Agent("agent", env, stimulus_types={"stimulus": Outer})
    task = cocotb.start_soon(agent.stimuli["stimulus"].execute())
    await Timer(5, unit="ns")
    agent.apply_reset()
    results.append(await task)
    assert results == [False] and after == []


@cocotb.test()
async def stimulus_failure_still_reaches_the_caller_of_execute(dut):
    class Fails(Stimulus):
        async def run(self):
            raise ValueError("boom")

    env = TbEnv("env", dut)
    try:
        await Fails("stimulus", env).execute()
    except ValueError:
        return
    raise AssertionError("failure was swallowed")


@cocotb.test()
async def reset_kills_spawned_tasks_and_restarts_run_loops(dut):
    starts, spawned_finished = [], []

    async def background():
        await Timer(1, unit="ms")
        spawned_finished.append(True)

    class Worker(Component):
        async def run(self):
            starts.append(get_sim_time(unit="ns"))
            self.spawn(background())
            await Event().wait()

    class Parent(Agent):
        pass

    class Pulses(Stimulus):
        async def run(self):
            await self.env.reset.wait_released()
            await Timer(5, unit="ns")
            await self.env.reset.pulse(duration_factor=1)
            await Timer(1, unit="ns")

    env = reset_env(dut, Pulses)
    agent = Parent("a", env, **domain_settings(dut))
    Worker("worker", agent)
    assert await failure_of(env) is None
    assert len(starts) == 3 and spawned_finished == []


@cocotb.test()
async def reset_only_reaches_the_agent_that_owns_the_uvc(dut):
    runs = {"reset": 0, "other": 0}

    class Worker(Component):
        def __init__(self, name, parent, key):
            super().__init__(name, parent)
            self.key = key

        async def run(self):
            runs[self.key] += 1
            await Event().wait()

    class Pulses(Stimulus):
        async def run(self):
            await self.env.reset.wait_released()
            await Timer(5, unit="ns")
            await self.env.reset.pulse(duration_factor=1)
            await Timer(1, unit="ns")

    env = reset_env(dut, Pulses)
    Worker("worker", Agent("in_domain", env, **domain_settings(dut)), "reset")
    Worker("worker", Agent("no_reset_uvc", env), "other")
    assert await failure_of(env) is None
    assert runs == {"reset": 3, "other": 1}


@cocotb.test()
async def nested_resets_release_only_when_all_are_released(dut):
    events = []

    class Watches(Component):
        def on_reset_asserted(self):
            events.append("asserted")

        def on_reset_released(self):
            events.append("released")

    env = TbEnv("env", dut)
    outer = Agent("outer", env)
    inner = Agent("inner", outer)
    Watches("watcher", inner)
    outer.apply_reset()
    inner.apply_reset()
    assert events == ["asserted"]
    outer.release_reset()
    assert events == ["asserted"]
    inner.release_reset()
    assert events == ["asserted", "released"]


@cocotb.test()
async def top_sequence_survives_a_reset_seen_at_the_top(dut):
    runs, finished = [], []

    class Toggles(Stimulus):
        async def run(self):
            runs.append(True)
            reset = self.env.dut.rst_n
            reset.value = 1
            await Timer(5, unit="ns")
            reset.value = 0
            await Timer(30, unit="ns")
            reset.value = 1
            await Timer(5, unit="ns")
            finished.append(True)

    env = TbEnv("env", dut, sequence_type=Toggles)
    env.reset = passive_reset("reset", env, interface=Interface(dut, rst_n="rst_n"))
    assert await failure_of(env) is None
    assert runs == [True] and finished == [True]


@cocotb.test()
async def sequence_starts_after_the_first_release(dut):
    states = []

    class Records(Stimulus):
        async def run(self):
            states.append(self.env.reset_handler.reset_state)

    assert await failure_of(restarting_env(dut, Records)) is None
    assert states == [ResetState.ResetInactive]


@cocotb.test()
async def sequence_restarts_after_a_reset(dut):
    runs, finished = [], []

    class RestartMe(Stimulus):
        async def run(self):
            runs.append(True)
            if len(runs) == 1:
                await Timer(1, unit="ms")
            finished.append(len(runs))

    env = restarting_env(dut, RestartMe)

    async def pulse_later():
        await Timer(100, unit="ns")
        await env.reset.pulse(duration_factor=1)

    cocotb.start_soon(pulse_later())
    assert await failure_of(env) is None
    assert len(runs) == 2 and finished == [2]


@cocotb.test()
async def sequence_can_apply_a_reset_without_restarting(dut):
    runs, finished = [], []

    class PulsesItself(Stimulus):
        async def run(self):
            runs.append(True)
            self.env.reset_handler.restart_sequence = False
            await self.env.reset.pulse(duration_factor=1)
            finished.append(True)

    assert await failure_of(restarting_env(dut, PulsesItself)) is None
    assert runs == [True] and finished == [True]


@cocotb.test()
async def failure_of_a_restartable_sequence_ends_the_run(dut):
    class Fails(Stimulus):
        async def run(self):
            raise ValueError("boom")

    assert "boom" in str(await failure_of(restarting_env(dut, Fails)))


@cocotb.test()
async def reset_flushes_the_queue_so_nothing_is_driven_during_reset(dut):
    class Pushes(Stimulus):
        async def run(self):
            await self.env.reset.wait_released()
            await Timer(5, unit="ns")
            for value in range(4):
                self.env.a.handler.queue(Transaction(value), driver="driver")
            await self.env.reset.pulse(duration_factor=2)

    driver_type = logging_driver()
    env = reset_agent_env(dut, Pushes, driver_type)
    assert await failure_of(env) is None
    assert driver_type.log == [] and env.a.handler.idle


@cocotb.test()
async def items_queued_during_reset_are_driven_after_release(dut):
    class PushesDuring(Stimulus):
        async def run(self):
            await self.env.reset.wait_released()
            pulse = cocotb.start_soon(self.env.reset.pulse(duration_factor=2))
            await Timer(1, unit="ns")
            self.env.a.handler.queue(Transaction(7), driver="driver")
            await pulse

    driver_type = logging_driver()
    assert await failure_of(reset_agent_env(dut, PushesDuring, driver_type)) is None
    assert driver_type.log == [(7, "1")]


@cocotb.test()
async def queued_pulse_counts_as_reset_for_waiters(dut):
    elapsed = []

    class PushThenWait(Stimulus):
        async def run(self):
            await self.env.reset.wait_released()
            start = get_sim_time(unit="ns")
            self.env.reset.handler.queue(Transaction(2), driver="driver")
            await self.env.reset.wait_released()
            elapsed.append(get_sim_time(unit="ns") - start)

    assert await failure_of(reset_env(dut, PushThenWait)) is None
    assert elapsed[0] >= 20


@cocotb.test()
async def queueing_without_a_registered_driver_is_an_error(dut):
    try:
        Handler("handler", TbEnv("env", dut)).queue(Transaction(1), driver="driver")
    except RuntimeError as error:
        assert "no driver registered" in str(error)
        return
    raise AssertionError("the item was queued")


@cocotb.test()
async def scoreboards_need_a_clock_unless_drain_is_off(dut):
    env = TbEnv("env", dut, sequence_type=Quick)
    ScoreboardAgent("agent", env)
    assert "heartbeat_clock" in str(await failure_of(env))

    env = TbEnv("env", dut, sequence_type=Quick, drain_cycles=0)
    ScoreboardAgent("agent", env)
    assert await failure_of(env) is None


@cocotb.test()
async def scoreboard_without_traffic_is_not_an_error(dut):
    start_clock(dut)
    env = scoreboard_env(dut)
    assert await failure_of(env) is None
    assert env.error_count == 0


@cocotb.test()
async def clock_agent_drives_the_requested_period(dut):
    assert await measured_clock_period(dut, 10) == 10000


@cocotb.test()
async def clock_agent_accepts_fractional_periods(dut):
    assert await measured_clock_period(dut, 3.3) == 3300


@cocotb.test()
async def checking_clock_agent_has_only_a_monitor(dut):
    env = passive_clock_env(dut, check_period=True)
    assert env.clock.monitors["monitor"] is not None and not env.clock.drivers
    assert await failure_of(env) is None


@cocotb.test()
async def passive_clock_agent_observes_without_period_checks(dut):
    env = passive_clock_env(dut, period_ns=20)
    assert not env.clock.drivers and type(env.clock.monitors["monitor"]) is Monitor
    assert await failure_of(env) is None


@cocotb.test()
async def enabled_clock_check_runs_every_window(dut):
    env = passive_clock_env(dut, period_ns=10, check_period=True, check_cycles=10)
    seen = []
    env.clock.monitors["monitor"].add_callback(seen.append)
    assert await failure_of(env) is None
    assert env.clock.monitors["monitor"].windows >= 2
    assert len(seen) == 1


@cocotb.test()
async def enabled_clock_check_finds_a_wrong_period(dut):
    env = passive_clock_env(dut, period_ns=20, check_period=True, check_cycles=10)
    assert "Clock period wrong" in str(await failure_of(env))


@cocotb.test()
async def clock_check_defaults_to_a_few_hundred_cycles(dut):
    env = passive_clock_env(dut, check_period=True)
    assert env.clock.monitors["monitor"].check_cycles == 500
    assert await failure_of(env) is None
    assert env.clock.monitors["monitor"].windows == 0


@cocotb.test()
async def clock_check_options_are_validated(dut):
    env = TbEnv("env", dut)
    settings = {"interface": Interface(dut, clk="clk")}
    bad = ({"active": False, "check_cycles": 100},
           {"active": True, "check_period": True})
    for index, options in enumerate(bad):
        try:
            ClockAgent(f"clock{index}", env, **settings, **options)
        except ValueError:
            continue
        raise AssertionError(f"accepted {options}")


@cocotb.test()
async def passive_reset_agent_has_only_a_monitor(dut):
    env = passive_reset_env(dut, 30)
    seen = []
    env.reset.monitors["monitor"].add_callback(seen.append)
    assert env.reset.monitors["monitor"] is not None and not env.reset.drivers
    assert await failure_of(env) is None
    assert env.reset.monitors["monitor"].pulse_durations_ns == [30]
    assert [item.data["asserted"] for item in seen] == [True, False]


@cocotb.test()
async def passive_reset_checks_width_at_the_toggle(dut):
    assert "Reset lasted" in str(await failure_of(passive_reset_env(dut, 5)))


@cocotb.test()
async def passive_reset_ignores_a_pulse_with_an_unknown_start(dut):
    class ReleaseSoon(Stimulus):
        async def run(self):
            await Timer(1, unit="ns")
            self.env.dut.rst_n.value = 1
            await self.env.reset.wait_released()

    dut.rst_n.value = 0
    await Timer(1, unit="ns")
    env = TbEnv("env", dut, sequence_type=ReleaseSoon)
    env.reset = ResetAgent("reset", env, active=False, reset_signal="rst_n", active_high=False,
                           interface=Interface(dut, rst_n="rst_n"))
    assert await failure_of(env) is None
    assert env.reset.monitors["monitor"].pulse_durations_ns == []


@cocotb.test()
async def reset_can_repeat(dut):
    class Twice(Stimulus):
        async def run(self):
            reset = self.env.dut.rst_n
            await self.env.reset.wait_released()
            self.env.dut.s_valid_i.value = 0  # legal: woken outside ReadOnly
            await ClockCycles(self.env.dut.clk, 2)
            assert str(reset.value) == "1"
            pulse = cocotb.start_soon(self.env.reset.pulse(duration_factor=1))
            await Timer(1, unit="ns")
            assert str(reset.value) == "0"
            await pulse
            await Timer(1, unit="ns")
            assert str(reset.value) == "1"

    env = reset_env(dut, Twice)
    assert await failure_of(env) is None
    assert "monitor" in env.reset.monitors


@cocotb.test()
async def reset_can_release_on_a_falling_edge(dut):
    class Observe(Stimulus):
        async def run(self):
            await self.env.reset.wait_released()
            times.append(get_sim_time(unit="step"))
            assert str(self.env.dut.clk.value) == "0"

    times = []
    env = reset_env(dut, Observe, duration_factor=2.5)
    env.reset.drivers["driver"].release_clock = dut.clk
    assert await failure_of(env) is None
    assert times


@cocotb.test()
async def resets_do_not_keep_the_heartbeat_alive(dut):
    class ResetsOften(Stimulus):
        async def run(self):
            for _ in range(10):
                watcher.apply_reset()
                await ClockCycles(self.env.dut.clk, 1)
                watcher.release_reset()
                await ClockCycles(self.env.dut.clk, 1)

    start_clock(dut)
    # No drain: the heartbeat can only fire while the resets are happening.
    env = TbEnv("env", dut, sequence_type=ResetsOften, heartbeat_clock=dut.clk, heartbeat_timeout=3,
                drain_cycles=0)
    watcher = ScoreboardAgent("watcher", env)
    assert "Heartbeat timeout" in str(await failure_of(env))


@cocotb.test()
async def reset_uvc_items_do_not_reach_the_agents_scoreboard(dut):
    seen = []

    class Board(Scoreboard):
        def process(self, item):
            seen.append(item.data)

    class Pulses(Stimulus):
        async def run(self):
            await self.env.reset.wait_released()
            await Timer(5, unit="ns")
            await self.env.reset.pulse(duration_factor=3)
            await Timer(5, unit="ns")

    config = tb_json({"clock": {"signal": "dut.clk"}, "reset": {"signal": "dut.rst_n", "active_high": False},
                         "watch": {"active": False, "p": port_file(), "monitor": True}})
    env = TbEnv("env", dut, tb_config=config, sequence_type=Pulses, drain_cycles=0)
    Board("scoreboard", env.agents["watch"])
    assert await failure_of(env) is None
    assert seen == []


@cocotb.test()
async def json_reset_does_not_restart_by_default(dut):
    runs = []

    class PulsesItself(Stimulus):
        async def run(self):
            runs.append(True)
            await self.env.reset.wait_released()
            await self.env.reset.pulse(duration_factor=1)

    config = tb_json({"clock": {"signal": "dut.clk"}, "reset": {"signal": "dut.rst_n", "active_high": False}})
    env = TbEnv("env", dut, tb_config=config, sequence_type=PulsesItself)
    assert env.reset_handler.restart_sequence is False
    assert await failure_of(env) is None and runs == [True]

    config = tb_json({"clock": {"signal": "dut.clk"},
                         "reset": {"signal": "dut.rst_n", "active_high": False, "restart_sequence": True}})
    assert TbEnv("env", dut, tb_config=config).reset_handler.restart_sequence is True


@cocotb.test()
async def components_held_in_reset_start_only_on_release(dut):
    started = []

    class Worker(Component):
        async def run(self):
            started.append((get_sim_time(unit="ns"), self.in_reset))

    class HeldAgent(Agent):
        def configure(self):
            self.apply_reset()

    class Releases(Stimulus):
        async def run(self):
            await Timer(10, unit="ns")
            self.env.held.release_reset()
            await Timer(1, unit="ns")

    env = TbEnv("env", dut, sequence_type=Releases)
    env.held = HeldAgent("held", env)
    Worker("worker", env.held)
    start = get_sim_time(unit="ns")
    assert await failure_of(env) is None
    assert len(started) == 1 and started[0][1] is False and started[0][0] - start >= 10, started


@cocotb.test()
async def stimulus_send_reports_an_aborted_item(dut):
    results = []

    class Slow(Driver):
        async def drive(self, item):
            await Timer(100, unit="ns")

    class Survives(Stimulus):
        async def run(self):
            await self.env.reset.wait_released()
            sender = cocotb.start_soon(self.send(Transaction("aborted"), driver="a.driver"))
            await Timer(5, unit="ns")
            await self.env.reset.pulse(duration_factor=1)
            results.append(await sender)
            results.append(await self.send(Transaction("driven"), driver="a.driver"))

    env = reset_env(dut, Survives)
    env.a = Agent("a", env, driver_types={"driver": Slow}, interface=Interface(dut, clk="clk"),
                  **domain_settings(dut))
    assert await failure_of(env) is None
    assert results == [False, True]
