"""Self-tests: Scoreboards, drain, handlers, handler state, monitors, and transactions."""
import cocotb

from support import *  # noqa: F401,F403  shared helpers and fixtures


@cocotb.test()
async def drain_allows_protocol_scoreboard_to_finish(dut):
    env = pipe_env(dut)
    assert await failure_of(env) is None
    board = env.pipe.scoreboards["scoreboard"]
    assert (board.begun, board.ended, len(board.pending)) == (3, 3, 0)
    assert len(board.transactions) == 6


@cocotb.test()
async def hung_transaction_fails_through_the_heartbeat(dut):
    class Hangs(Stimulus):
        async def run(self):
            await Timer(1, unit="us")

    start_clock(dut)
    failure = await failure_of(scoreboard_env(dut, sequence_type=Hangs, heartbeat_timeout=20))
    assert "Heartbeat timeout" in str(failure)


@cocotb.test()
async def scoreboard_history_is_bounded(dut):
    board = Scoreboard("board", TbEnv("env", dut), history=2)
    for value in range(5):
        board.callback(Transaction(value))
    assert [item.data for item in board.transactions] == [3, 4]


@cocotb.test()
async def agent_registers_every_driver_with_its_one_handler(dut):
    env = TbEnv("env", dut, sequence_type=Quick)
    agent = Agent("agent", env, driver_types={"a": RecordingDriver, "b": RecordingDriver},
                  interface=Interface(dut, clk="clk"))
    assert agent.handler.drivers == {} and sum(isinstance(c, Handler) for c in agent.children) == 1
    assert await failure_of(env) is None
    for key in ("a", "b"):
        assert agent.handler.drivers[key] is agent.drivers[key]
        assert agent.drivers[key].handler is agent.handler


class KeepsItems(Driver):
    """Records the items it drives, with their trace fields."""

    def __init__(self, name, parent=None, **kwargs):
        super().__init__(name, parent, **kwargs)
        self.items = []

    async def drive(self, item):
        await Timer(1, unit="ns")
        self.items.append(item)


@cocotb.test()
async def sequences_share_one_handler_and_record_their_paths(dut):
    class Inner(Stimulus):
        async def run(self):
            self.queue(Transaction("inner to b"), driver="b")
            await self.send(Transaction("inner sends a"), driver="a")

    class First(Stimulus):
        def __init__(self, name, parent=None):
            super().__init__(name, parent)
            self.inner = Inner("inner", self)

        async def run(self):
            assert self.handler is self.agent.handler
            self.queue(Transaction("first to a"), driver="a")
            await self.inner.execute()
            await self.wait_idle()

    class Second(Stimulus):
        async def run(self):
            self.handler.queue(Transaction("direct to b"), driver="b")
            self.queue(Transaction("second to b"), driver="b")
            await self.wait_idle()

    class Coordinates(Stimulus):
        def __init__(self, name, parent=None):
            super().__init__(name, parent)
            self.first = First("first", self)
            self.second = Second("second", self)

        async def run(self):
            await self.first.execute()
            await self.second.execute()

    env = TbEnv("env", dut)
    agent = Agent("agent", env, driver_types={"a": KeepsItems, "b": KeepsItems},
                  stimulus_types={"stimulus": Coordinates}, interface=Interface(dut, clk="clk"))
    env.stimulus = agent.stimuli["stimulus"]
    assert await failure_of(env) is None
    assert sum(isinstance(child, Handler) for child in agent.children) == 1
    driven = {item.data: (item.sequence, item.driver, item.source)
              for name in ("a", "b") for item in agent.drivers[name].items}
    assert driven == {
        "first to a": ("env.agent.stimulus.first", "env.agent.a", "env.agent.stimulus.first"),
        "inner sends a": ("env.agent.stimulus.first.inner", "env.agent.a", "env.agent.stimulus.first.inner"),
        "inner to b": ("env.agent.stimulus.first.inner", "env.agent.b", "env.agent.stimulus.first.inner"),
        "second to b": ("env.agent.stimulus.second", "env.agent.b", "env.agent.stimulus.second"),
        "direct to b": (None, "env.agent.b", "env.agent.handler"),
    }, driven


@cocotb.test()
async def resent_item_records_the_latest_sequence(dut):
    item = Transaction("reused", source="env.elsewhere")

    class Resends(Stimulus):
        async def run(self):
            await self.send(item, driver="driver")

    env = TbEnv("env", dut)
    agent = Agent("agent", env, driver_types={"driver": KeepsItems}, stimulus_types={"stimulus": Resends},
                  interface=Interface(dut, clk="clk"))
    env.stimulus = agent.stimuli["stimulus"]
    assert await failure_of(env) is None
    assert (item.source, item.sequence, item.driver) == ("env.elsewhere", "env.agent.stimulus", "env.agent.driver")
    assert "sequence='env.agent.stimulus'" in repr(item)


@cocotb.test()
async def a_wrong_driver_path_is_an_error(dut):
    env = TbEnv("env", dut)
    top = RecordingAgent("top", env, interface=Interface(dut, clk="clk"))
    RecordingAgent("child", top, interface=Interface(dut, clk="clk"))
    Monitor("monitor", top)
    stimulus = Stimulus("stimulus", top)
    for path in ("nothing", "child.nothing", "monitor", "child", ""):
        try:
            stimulus.queue(Transaction(1), driver=path)
        except ValueError as error:
            assert "is not a driver" in str(error) and "child.driver" in str(error), error
            continue
        raise AssertionError(f"accepted driver path {path!r}")


@cocotb.test()
async def a_driver_registers_with_only_one_handler(dut):
    env = TbEnv("env", dut)
    driver = RecordingDriver("driver", env)
    Handler("first", env).register_driver(driver)
    try:
        Handler("second", env).register_driver(driver)
    except ValueError:
        return
    raise AssertionError("a driver was registered twice")


@cocotb.test()
async def the_driver_is_always_named_even_with_one_driver(dut):
    env = TbEnv("env", dut)
    agent = Agent("agent", env, driver_types={"only": RecordingDriver}, interface=Interface(dut, clk="clk"))
    agent.connect()
    stimulus = Stimulus("stimulus", agent)
    for call in (lambda: agent.handler.queue(Transaction(1)),
                 lambda: stimulus.queue(Transaction(1))):
        try:
            call()
        except TypeError as error:
            assert "driver" in str(error)
            continue
        raise AssertionError("a driver name was not required")

    try:
        agent.handler.queue(Transaction(1), driver="other")
    except ValueError as error:
        assert "only" in str(error)
    else:
        raise AssertionError("an unknown driver was accepted")


@cocotb.test()
async def stimulus_queues_for_any_driver_by_path(dut):
    class Pushes(Stimulus):
        async def run(self):
            self.queue(Transaction("top"), driver="driver")
            self.queue(Transaction("child"), driver="child.driver")
            await self.wait_idle()
            done.append(get_sim_time(unit="ns"))

    done = []
    env = TbEnv("env", dut, sequence_type=None)
    top = RecordingAgent("top", env, stimulus_types={"stimulus": Pushes}, interface=Interface(dut, clk="clk"))
    RecordingAgent("child", top, interface=Interface(dut, clk="clk"))
    env.stimulus = top.stimuli["stimulus"]
    assert await failure_of(env) is None
    assert top.drivers["driver"].seen == ["top"]
    assert top.children[-1].drivers["driver"].seen == ["child"]
    assert done and done[0] >= 1


@cocotb.test()
async def queued_items_are_driven_in_order_before_the_run_ends(dut):
    class Pushes(Stimulus):
        async def run(self):
            for value in (1, 2, 3):
                self.env.agent.handler.queue(Transaction(value), driver="driver")
            assert not self.env.agent.handler.idle

    env = TbEnv("env", dut, sequence_type=Pushes)
    env.agent = RecordingAgent("agent", env, interface=Interface(dut, clk="clk"))
    assert await failure_of(env) is None
    assert env.agent.drivers["driver"].seen == [1, 2, 3] and env.agent.handler.idle


@cocotb.test()
async def each_driver_pops_only_its_own_queue(dut):
    class Pushes(Stimulus):
        async def run(self):
            self.env.agent.handler.queue(Transaction("for a"), driver="a")
            self.env.agent.handler.queue(Transaction("for b"), driver="b")

    env = TbEnv("env", dut, sequence_type=Pushes)
    env.agent = Agent("agent", env, driver_types={"a": RecordingDriver, "b": RecordingDriver},
                      interface=Interface(dut, clk="clk"))
    assert await failure_of(env) is None
    assert env.agent.drivers["a"].seen == ["for a"] and env.agent.drivers["b"].seen == ["for b"]


@cocotb.test()
async def handler_tags_the_source(dut):
    env = TbEnv("env", dut)
    item = Transaction(1)
    handler = Handler("handler", env)
    handler.register_driver(RecordingDriver("driver", env))
    handler.queue(item, driver="driver")
    assert item.source == "env.handler"


@cocotb.test()
async def failure_of_a_queued_item_ends_the_run(dut):
    class Fails(Driver):
        async def drive(self, item):
            raise ValueError("drive failed")

    class Pushes(Stimulus):
        async def run(self):
            self.env.agent.handler.queue(Transaction(1), driver="driver")

    env = TbEnv("env", dut, sequence_type=Pushes)
    env.agent = Agent("agent", env, driver_types={"driver": Fails}, interface=Interface(dut, clk="clk"))
    assert "drive failed" in str(await failure_of(env))


@cocotb.test()
async def monitor_callback_can_feed_another_agents_handler(dut):
    class WritesAtOnce(Driver):
        async def drive(self, item):
            self.interface.s_valid_i.value = 1
            driven.append(item.data)

    class Publishes(Monitor):
        async def run(self):
            await RisingEdge(self.interface.clk)
            await ReadOnly()
            self.publish(Transaction("from monitor"))

    class Connected(Agent):
        def connect(self):
            super().connect()
            source.monitors["monitor"].add_callback(lambda item: self.handler.queue(item, driver="driver"))

    driven = []
    start_clock(dut)
    interface = Interface(dut, clk="clk", s_valid_i="s_valid_i")
    env = TbEnv("env", dut, sequence_type=Cycles, sequence_config={"cycles": 3})
    source = Agent("source", env, monitor_types={"monitor": Publishes}, interface=interface)
    Connected("sink", env, driver_types={"driver": WritesAtOnce}, interface=interface)
    assert await failure_of(env) is None
    assert driven == ["from monitor"]


@cocotb.test()
async def reset_driver_serves_its_handler_after_startup(dut):
    class PulseThroughHandler(Stimulus):
        async def run(self):
            await self.env.reset.wait_released()
            await ClockCycles(self.env.dut.clk, 2)
            self.env.reset.handler.queue(Transaction(1), driver="driver")
            await self.env.reset.handler.wait_idle()
            assert str(self.env.dut.rst_n.value) in ("0", "1")
            pulses.append(True)

    pulses = []
    env = reset_env(dut, PulseThroughHandler)
    assert await failure_of(env) is None
    assert pulses == [True]


@cocotb.test()
async def clock_agent_has_its_own_handler(dut):
    env = clock_env(dut, period_ns=10)
    assert isinstance(env.clock.handler, Handler)
    assert await failure_of(env) is None


@cocotb.test()
async def reset_state_follows_each_pulse(dut):
    states = []

    class Observes(Stimulus):
        async def run(self):
            handler = self.env.reset.handler
            states.append(handler.reset_state)
            await handler.wait_released()
            states.append(handler.reset_state)
            pulse = cocotb.start_soon(self.env.reset.pulse(duration_factor=1))
            await Timer(1, unit="ns")
            states.append(handler.reset_state)
            await pulse
            states.append(handler.reset_state)

    env = reset_env(dut, Observes)
    assert isinstance(env.reset.handler, ResetHandler)
    assert await failure_of(env) is None
    assert states == [ResetState.ResetActive, ResetState.ResetInactive,
                      ResetState.ResetActive, ResetState.ResetInactive]


@cocotb.test()
async def extended_handler_state_is_a_plain_attribute(dut):
    class LinkHandler(Handler):
        def __init__(self, name, parent=None):
            super().__init__(name, parent)
            self.link_up = False

    class LinkAgent(RecordingAgent):
        handler_type = LinkHandler

    class WaitsForLink(Stimulus):
        async def run(self):
            handler = self.env.agent.handler
            cocotb.start_soon(bring_up(handler))
            while not handler.link_up:
                await Timer(1, unit="ns")
            handler.queue(Transaction("after link up"), driver="driver")

    async def bring_up(handler):
        await Timer(3, unit="ns")
        handler.link_up = True

    env = TbEnv("env", dut, sequence_type=WaitsForLink)
    env.agent = LinkAgent("agent", env, interface=Interface(dut, clk="clk"))
    assert await failure_of(env) is None
    assert env.agent.drivers["driver"].seen == ["after link up"]


@cocotb.test()
async def in_reset_is_a_plain_flag_with_a_wait(dut):
    env = TbEnv("env", dut)
    agent = Agent("agent", env)
    worker = Component("worker", agent)
    assert worker.in_reset is False
    agent.apply_reset()
    assert worker.in_reset is True
    waiter = cocotb.start_soon(worker.wait_out_of_reset())
    await Timer(1, unit="ns")
    assert not waiter.done()
    agent.release_reset()
    await waiter
    assert worker.in_reset is False


@cocotb.test()
async def publish_changed_skips_repeats(dut):
    env = TbEnv("env", dut)
    monitor = Monitor("monitor", env)
    seen = []
    monitor.add_callback(seen.append)
    for value in (1, 1, 2, 2, 1):
        monitor.publish_changed(Transaction(value))
    assert [item.data for item in seen] == [1, 2, 1]


@cocotb.test()
async def monitor_requires_an_interface(dut):
    env = TbEnv("env", dut, sequence_type=Quick)
    Monitor("monitor", env)
    assert "requires an interface" in str(await failure_of(env))


@cocotb.test()
async def random_streams_depend_on_path_only(dut):
    first = TbEnv("env", dut)
    Agent("noise", first)
    one = Agent("a", first).random.random()
    second = TbEnv("env", dut)
    two = Agent("a", second).random.random()
    assert one == two


@cocotb.test()
async def transactions_are_hashable_and_subclassable(dut):
    @dataclass
    class Item(Transaction):
        address: int = 0

    assert hash(Transaction(1)) == hash(Transaction(1))
    item = Item(address=4)
    assert item.source is None
    monitor = Monitor("monitor", TbEnv("env", dut))
    monitor.publish(item)
    assert item.source == "env.monitor"


@cocotb.test()
async def explicit_empty_overrides_disable_inherited_components(dut):
    class Full(RecordingAgent):
        monitor_types = {"monitor": Monitor}
        stimulus_types = {"stimulus": Quick}
        scoreboard_types = {"scoreboard": Scoreboard}
        agent_types = {"child": RecordingAgent}

    env = TbEnv("env", dut)
    inherited = Full("inherited", env, interface=Interface(dut, clk="clk"))
    assert inherited.drivers and inherited.monitors and inherited.stimuli and inherited.agents
    assert inherited.scoreboards and inherited.handler is not None

    empty = Full("empty", env, driver_types={}, monitor_types={}, stimulus_types={}, agent_types={},
                 scoreboard_types={}, interface=Interface(dut, clk="clk"))
    assert not (empty.drivers or empty.monitors or empty.stimuli or empty.agents)
    assert not empty.scoreboards and isinstance(empty.handler, Handler)

    no_handler = Full("no_handler", env, handler_type=None, stimulus_types={}, interface=Interface(dut, clk="clk"))
    assert no_handler.drivers and no_handler.handler is None


@cocotb.test()
async def top_level_sequence_reaches_drivers_by_path_from_the_env(dut):
    class Top(Stimulus):
        async def run(self):
            self.queue(Transaction("queued"), driver="agent.driver")
            await self.send(Transaction("sent"), driver="agent.child.driver")
            await self.wait_idle()

    env = TbEnv("env", dut, sequence_type=Top)
    agent = RecordingAgent("agent", env, interface=Interface(dut, clk="clk"))
    RecordingAgent("child", agent, interface=Interface(dut, clk="clk"))
    assert await failure_of(env) is None
    assert agent.drivers["driver"].seen == ["queued"]
    assert agent.agents["child"].drivers["driver"].seen == ["sent"]


@cocotb.test()
async def queueing_to_a_driver_without_a_handler_is_a_clear_error(dut):
    env = TbEnv("env", dut)
    agent = RecordingAgent("agent", env, handler_type=None, interface=Interface(dut, clk="clk"))
    try:
        Stimulus("s", agent).queue(Transaction(1), driver="driver")
    except ValueError as error:
        assert "has no handler" in str(error) and "send()" in str(error)
        return
    raise AssertionError("queueing without a handler was accepted")


@cocotb.test()
async def passive_agent_rejects_drivers_and_stimulus(dut):
    env = TbEnv("env", dut)
    for kwargs in ({"driver_types": {"driver": RecordingDriver}}, {"stimulus_types": {"stimulus": Quick}}):
        try:
            Agent("passive", env, active=False, **kwargs)
        except ValueError as error:
            assert "passive agent" in str(error)
            continue
        raise AssertionError(f"accepted {kwargs}")

    # Reusing an active agent class passively still works: its class defaults are skipped.
    passive = RecordingAgent("reused", env, active=False)
    assert not passive.drivers and isinstance(passive.handler, Handler)


@cocotb.test()
async def agents_lists_every_child_agent(dut):
    env = TbEnv("env", dut)
    top = Agent("top", env)
    Agent("added_later", top)
    assert set(env.agents) == {"top"} and set(top.agents) == {"added_later"}


@cocotb.test()
async def watchdog_names_what_is_still_busy(dut):
    class Hangs(Stimulus):
        async def run(self):
            self.env.handler.queue(Transaction("never sent"), driver="driver")

    env = TbEnv("env", dut, sequence_type=Hangs, timeout=1, timeout_unit="us", drain_cycles=0, max_errors=5)
    env.handler = Handler("handler", env)
    env.handler.register_driver(Driver("driver", interface=Interface(dut, clk="clk")))
    assert "still busy: env.handler" in str(await failure_of(env))


@cocotb.test()
async def transactions_convert_to_and_from_interface_values(dut):
    @dataclass
    class PortItem(Transaction):
        valid: object = None
        data: object = None

    interface = Interface(dut, valid="s_valid_i", data="s_data_i", clk="clk", tags={"clk": "Clock"})
    dut.s_valid_i.value, dut.s_data_i.value = 1, 0x5A
    await Timer(1, unit="ns")
    interface._sample()
    item = PortItem.from_values(interface.values)
    assert (item.valid, int(item.data)) == (1, 0x5A) and item.source is None
    assert PortItem(valid=0).signal_values() == {"valid": 0}
    dut.s_valid_i.value = 0


@cocotb.test()
async def resetting_one_driver_frees_its_queue(dut):
    class Slow(Driver):
        async def drive(self, item):
            await Timer(100, unit="ns")

    class ResetsTheDriver(Stimulus):
        async def run(self):
            driver = self.env.agents["agent"].drivers["driver"]
            self.queue(Transaction(1), driver="agent.driver")
            await Timer(5, unit="ns")
            driver.apply_reset()
            # Would hang until the watchdog if the killed item left the queue busy.
            await self.wait_idle()
            driver.release_reset()

    env = TbEnv("env", dut, sequence_type=ResetsTheDriver, timeout=1, timeout_unit="us")
    Agent("agent", env, driver_types={"driver": Slow}, interface=Interface(dut, clk="clk"))
    assert await failure_of(env) is None


@cocotb.test()
async def wait_released_covers_a_pulse_just_requested(dut):
    measured = []

    class Pulses(Stimulus):
        async def run(self):
            await self.env.reset.wait_released()
            cocotb.start_soon(self.env.reset.pulse(duration_factor=2))
            start = get_sim_time(unit="ns")
            await self.env.reset.wait_released()
            measured.append(get_sim_time(unit="ns") - start)

    env = reset_env(dut, Pulses)
    assert await failure_of(env) is None
    assert measured and measured[0] >= 20, measured


class TimesItems(Driver):
    """Records when each item starts, in clock cycles; each takes one cycle to drive."""

    def __init__(self, name, parent=None, **kwargs):
        super().__init__(name, parent, **kwargs)
        self.starts = []

    async def drive(self, item):
        self.starts.append(get_sim_time(unit="ns") // 10)
        await RisingEdge(self.interfaces["default"].clk)


def delay_env(dut, sequence_type, **driver_settings):
    start_clock(dut)
    env = TbEnv("env", dut, sequence_type=sequence_type, timeout=10, timeout_unit="us")
    agent = Agent("agent", env, driver_types={"driver": TimesItems},
                  interface=Interface(dut, clk="clk", tags={"clk": "Clock"}))
    for key, value in driver_settings.items():
        setattr(agent.drivers["driver"], key, value)
    return env, agent.drivers["driver"]


@cocotb.test()
async def queued_items_wait_their_delay_in_clock_cycles(dut):
    class Spaced(Stimulus):
        async def run(self):
            await RisingEdge(self.env.dut.clk)
            for _ in range(3):
                self.queue(Transaction(0), driver="agent.driver", delay=3)
            await self.wait_idle()

    env, driver = delay_env(dut, Spaced)
    assert await failure_of(env) is None
    gaps = [later - earlier for earlier, later in zip(driver.starts, driver.starts[1:])]
    # One cycle to drive, then three cycles of delay before the next item.
    assert gaps == [4, 4], driver.starts


@cocotb.test()
async def max_delay_waits_a_random_bounded_number_of_cycles(dut):
    class Random(Stimulus):
        async def run(self):
            await RisingEdge(self.env.dut.clk)
            for _ in range(30):
                self.queue(Transaction(0), driver="agent.driver", max_delay=4)
            await self.wait_idle()

    class UsesTheDriverDefault(Stimulus):
        async def run(self):
            await RisingEdge(self.env.dut.clk)
            for _ in range(30):
                self.queue(Transaction(0), driver="agent.driver")
            await self.wait_idle()

    for sequence_type, settings in ((Random, {}), (UsesTheDriverDefault, {"max_delay": 4})):
        env, driver = delay_env(dut, sequence_type, **settings)
        assert await failure_of(env) is None
        waits = [later - earlier - 1 for earlier, later in zip(driver.starts, driver.starts[1:])]
        assert all(0 <= wait <= 4 for wait in waits) and len(set(waits)) > 1, waits

    # The driver's seeded stream makes the delays repeat run to run.
    first = list(waits)
    env, driver = delay_env(dut, UsesTheDriverDefault, max_delay=4)
    assert await failure_of(env) is None
    assert [later - earlier - 1 for earlier, later in zip(driver.starts, driver.starts[1:])] == first


@cocotb.test()
async def queue_delays_are_checked(dut):
    env, driver = delay_env(dut, None)
    env._phase("connect")
    handler = env.agents["agent"].handler
    for kwargs, expected in (({"delay": -1}, "non-negative"), ({"max_delay": 1.5}, "non-negative"),
                             ({"delay": 1, "max_delay": 2}, "not both")):
        try:
            handler.queue(Transaction(0), driver="driver", **kwargs)
        except ValueError as error:
            assert expected in str(error), (kwargs, error)
        else:
            raise AssertionError(f"{kwargs} was accepted")

    untagged = Driver("untagged", env, interface=Interface(dut, clk="clk"))
    try:
        untagged._clock()
    except RuntimeError as error:
        assert "tag the interface's clock [Clock]" in str(error)
    else:
        raise AssertionError("a delay without a tagged clock was accepted")


@cocotb.test()
async def drive_values_names_an_interface_only_when_there_is_a_choice(dut):
    env = TbEnv("env", dut)
    one = Driver("one", env, interface=Interface(dut, valid="s_valid_i"))
    one.drive_values(valid=1)
    await Timer(1, unit="ns")
    assert dut.s_valid_i.value == 1
    one.drive_values(valid=0)

    two = Driver("two", env, interfaces={"a": Interface(dut, valid="s_valid_i"), "b": Interface(dut, clk="clk")})
    try:
        two.drive_values(valid=1)
    except ValueError as error:
        assert "select a bound interface from ['a', 'b']" in str(error)
    else:
        raise AssertionError("an unnamed interface was accepted with two bound")
    await Timer(1, unit="ns")


@cocotb.test()
async def idle_values_cover_every_field_and_array_element(dut):
    @dataclass
    class QueueItem(Transaction):
        stages: object = None
        valid: object = None

    assert QueueItem.idle_values() == {"stages": 0, "valid": 0}
    env = TbEnv("env", dut)
    driver = Driver("driver", env, interface=Interface(dut, stages="valid_q", valid="s_valid_i"))
    dut.s_valid_i.value = 1
    await Timer(1, unit="ns")
    driver.drive_values(**QueueItem.idle_values())
    await ReadOnly()
    # One value fills every element of the array signal.
    assert [int(stage) for stage in dut.valid_q.value] == [0, 0] and dut.s_valid_i.value == 0
    await Timer(1, unit="ns")

