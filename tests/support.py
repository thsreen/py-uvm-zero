"""Shared helpers, fixtures, and stimulus for the framework self-tests."""
from asyncio import CancelledError
from collections import deque
from dataclasses import dataclass
from enum import Enum, auto
import json
import os
import tempfile
from pathlib import Path
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, Event, FallingEdge, ReadOnly, RisingEdge, Timer
from cocotb.utils import get_sim_time
from agent.agent.agent_port_json_monitor import AgentPortJsonMonitor as JsonMonitor
from agent.agent.agent_slave_json_monitor import AgentSlaveJsonMonitor as SlaveJsonMonitor
from agent.seqs.agent_json_stimulus import AgentJsonStimulus as JsonStimulus
from top.agent.top_left_span_child_driver import TopLeftSpanChildDriver as SpanChildDriver
from top.agent.top_spanning_driver import TopSpanningDriver as SpanningDriver
from common_uvc import ClockAgent, ResetAgent, ResetHandler, ResetState
from uvm_zero_base import (Agent, Component, Driver, Interface, Monitor, Scoreboard, Handler, Stimulus,
                      TbEnv, Transaction)
from uvm_zero_base.test_config import TestConfig
from uvm_zero_builder.build import subtree
from uvm_zero_builder.generate import main as generate_main, plan_files
from uvm_zero_builder.plan import ConfigError, load_plan, module_for


async def failure_of(env):
    """Run the environment and return its failure, or None when it passes."""
    try:
        await env.run_test()
    except (Exception, CancelledError) as error:
        return error
    return None


def start_clock(dut):
    Clock(dut.clk, 10, unit="ns").start()


class Quick(Stimulus):
    async def run(self):
        await Timer(1, unit="ns")


class Cycles(Stimulus):
    def __init__(self, name, parent=None, *, cycles=20):
        super().__init__(name, parent)
        self.cycles = cycles

    async def run(self):
        await ClockCycles(self.env.dut.clk, self.cycles)


class ScoreboardAgent(Agent):
    scoreboard_types = {"scoreboard": Scoreboard}


def scoreboard_env(dut, sequence_type=Cycles, **kwargs):
    kwargs.setdefault("heartbeat_clock", dut.clk)
    env = TbEnv("env", dut, sequence_type=sequence_type, **kwargs)
    ScoreboardAgent("agent", env)
    return env


class PipeDriver(Driver):
    async def drive(self, item):
        await FallingEdge(self.interface.clk)
        self.interface.s_valid_i.value = 1
        self.interface.s_data_i.value = item.data
        await FallingEdge(self.interface.clk)
        self.interface.s_valid_i.value = 0


class PipeMonitor(Monitor):
    """Report requests and responses; the source field distinguishes the two."""

    def __init__(self, name, parent=None, *, valid, data, kind, **kwargs):
        super().__init__(name, parent, **kwargs)
        self.valid, self.data, self.kind = valid, data, kind

    async def run(self):
        valid = getattr(self.interface, self.valid)
        data = getattr(self.interface, self.data)
        while True:
            await RisingEdge(self.interface.clk)
            await ReadOnly()
            if str(valid.value) == "1":
                self.publish(Transaction((self.kind, int(data.value))))


class PipeScoreboard(Scoreboard):
    """Protocol-owned matching; the base scoreboard does not track requests."""

    def __init__(self, name, parent=None):
        super().__init__(name, parent, history=100)
        self.pending = deque()
        self.begun = self.ended = 0

    def process(self, transaction):
        kind, value = transaction.data
        if kind == "request":
            self.pending.append(value)
            self.begun += 1
        elif not self.pending:
            self.error("Response without a request")
        else:
            expected = self.pending.popleft()
            self.ended += 1
            if value != expected:
                self.error(f"Data mismatch: sent {expected}, received {value}")

    def on_reset_asserted(self):
        self.pending.clear()

    def check_phase(self):
        if self.pending:
            self.error(f"{len(self.pending)} unanswered requests")


class PipeAgent(Agent):
    def connect(self):
        super().connect()
        board = self.scoreboards["scoreboard"]
        for monitor in self.monitors.values():
            board.subscribe(monitor, board.process)


def pipe_agent(name, parent, **kwargs):
    from functools import partial

    return PipeAgent(name, parent,
                     driver_types={"driver": PipeDriver},
                     monitor_types={
                         "requests": partial(PipeMonitor, valid="s_valid_i", data="s_data_i", kind="request"),
                         "responses": partial(PipeMonitor, valid="m_valid_o", data="m_data_o", kind="response"),
                     },
                     scoreboard_types={"scoreboard": PipeScoreboard}, **kwargs)


class SendThree(Stimulus):
    async def run(self):
        await ClockCycles(self.env.dut.clk, 5)
        for value in (1, 2, 3):
            await self.env.pipe.drivers["driver"].send(Transaction(value))


def pipe_env(dut, **kwargs):
    start_clock(dut)
    dut.s_valid_i.value = 0
    dut.s_data_i.value = 0
    env = TbEnv("env", dut, sequence_type=SendThree, heartbeat_clock=dut.clk, **kwargs)
    env.pipe = pipe_agent("pipe", env, interface=Interface(
        dut, clk="clk", s_valid_i="s_valid_i", s_data_i="s_data_i",
        m_valid_o="m_valid_o", m_data_o="m_data_o"))
    return env


class RecordingDriver(Driver):
    def __init__(self, name, parent=None, **kwargs):
        super().__init__(name, parent, **kwargs)
        self.seen = []

    async def drive(self, item):
        await Timer(1, unit="ns")
        self.seen.append(item.data)


class RecordingAgent(Agent):
    driver_types = {"driver": RecordingDriver}


def passive_reset(name, parent, **kwargs):
    return ResetAgent(name, parent, active=False, reset_signal="rst_n", active_high=False,
                      duration_factor=0.1, **kwargs)


def domain_settings(dut, **kwargs):
    """Constructor settings that give an agent its own passive reset UVC."""
    return {"agent_types": {"reset": passive_reset},
            "agent_options": {"reset": {"interface": Interface(dut, rst_n="rst_n")}}, **kwargs}


def reset_agent_env(dut, sequence_type, driver_type):
    env = reset_env(dut, sequence_type)
    env.a = Agent("a", env, driver_types={"driver": driver_type}, interface=Interface(dut, clk="clk"),
                  **domain_settings(dut))
    return env


class LogsResetLevel(Driver):
    log = None

    async def drive(self, item):
        await Timer(5, unit="ns")
        type(self).log.append((item.data, str(self.root.dut.rst_n.value)))


def logging_driver():
    return type("Logs", (LogsResetLevel,), {"log": []})


def restarting_env(dut, sequence_type):
    env = reset_env(dut, sequence_type)
    env.reset_handler = env.reset.handler
    env.reset_handler.restart_sequence = True
    return env


def materialize_infra(config):
    """Generate real infrastructure in the fixture directory before construction."""
    plan = load_plan(config)
    for path, source in plan_files(plan, Path(config).name).items():
        if "infra" in path.parts:
            target = Path(config).parent / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source)
    return config


def tb_json(body):
    path = Path(tempfile.mkdtemp()) / "tb.json"
    path.write_text(json.dumps(body))
    try:
        materialize_infra(path)
    except ConfigError:
        pass  # Invalid-config tests assert the actual loader's diagnostic.
    return str(path)


def port_file():
    return write_json({"signals": [".clk"]})


def config_problems(body):
    try:
        load_plan(tb_json(body))
    except ConfigError as error:
        return str(error).splitlines()
    return []


def generator_project():
    """A config, its interface files, and a fresh output directory."""
    directory = Path(tempfile.mkdtemp())
    (directory / "port.json").write_text(json.dumps({"signals": [".valid"]}))
    (directory / "named.json").write_text(json.dumps({"signals": [".valid -> id"]}))
    (directory / "tb.json").write_text(json.dumps({"gen": {
        "connected_module": "dut", "scoreboard": "GenScoreboard", "stimulus": "GenTraffic",
        "driver": "GenSpanDriver",
        "connections": ["GenNamedMonitor -> GenScoreboard", "GenLeftMonitor -> GenScoreboard",
                        "GenSlaveMonitor -> GenScoreboard"],
        "named": {"connected_module": ".b", "port": "named.json", "monitor": "GenNamedMonitor"},
        "left": {"connected_module": ".a", "port": "port.json",
                 "monitor": "GenLeftMonitor", "driver": "GenLeftDriver"},
        "slave[2]": {"connected_module": ".gen_blk[{i}].u", "port": "port.json", "monitor": "GenSlaveMonitor"},
    }}))
    return directory


def fill(path, replacements, imports=""):
    """Do what a user does: replace each NotImplementedError with real logic."""
    source = path.read_text()
    for old, new in replacements.items():
        assert old in source, (path.name, old)
        source = source.replace(old, new)
    path.write_text(source.replace("from uvm_zero_base import", imports + "from uvm_zero_base import", 1))


def valid_file():
    return write_json({"signals": [".valid"]})


def monitored_interface(env, *names):
    node = env.agents[names[0]]
    for name in names[1:]:
        node = node.agents[name]
    return next(iter(node.interfaces.values())), node


def clock_env(dut, sequence_type=Cycles, **kwargs):
    agent_settings = {"clock_signal": "clk", "interface": Interface(dut, clk="clk")}
    agent_settings.update(kwargs)
    env = TbEnv("env", dut, sequence_type=sequence_type)
    env.clock = ClockAgent("clock", env, **agent_settings)
    return env


async def measured_clock_period(dut, period_ns):
    periods = []

    class Measure(Stimulus):
        async def run(self):
            await RisingEdge(dut.clk)
            start = get_sim_time(unit="step")
            await RisingEdge(dut.clk)
            periods.append(get_sim_time(unit="step") - start)

    env = clock_env(dut, sequence_type=Measure, period_ns=period_ns)
    assert await failure_of(env) is None
    assert type(env.clock.monitors["monitor"]) is Monitor
    return periods[0]


def passive_clock_env(dut, cycles=30, **kwargs):
    start_clock(dut)
    env = TbEnv("env", dut, sequence_type=Cycles, sequence_config={"cycles": cycles})
    env.clock = ClockAgent("clock", env, active=False, clock_signal="clk",
                           interface=Interface(dut, clk="clk"), **kwargs)
    return env


def passive_reset_env(dut, width_ns):
    class External(Stimulus):
        async def run(self):
            reset = self.env.dut.rst_n
            reset.value = 1
            await Timer(5, unit="ns")
            reset.value = 0
            await Timer(width_ns, unit="ns")
            reset.value = 1
            await self.env.reset.wait_released()

    env = TbEnv("env", dut, sequence_type=External)
    env.reset = ResetAgent("reset", env, active=False, reset_signal="rst_n", active_high=False,
                           interface=Interface(dut, rst_n="rst_n"))
    return env


def reset_env(dut, sequence_type, **kwargs):
    env = TbEnv("env", dut, sequence_type=sequence_type)
    env.clock = ClockAgent("clock", env, clock_signal="clk", interface=Interface(dut, clk="clk"))
    env.reset = ResetAgent("reset", env, reset_signal="rst_n", active_high=False,
                           interface=Interface(dut, rst_n="rst_n"), **kwargs)
    return env


def write_json(body):
    handle, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(handle, "w", encoding="utf-8") as file:
        json.dump(body, file)
    return path


def expect_json_error(dut, body, text, **kwargs):
    try:
        Interface.from_json(dut, write_json(body) if not isinstance(body, str) else body, **kwargs)
    except ValueError as error:
        assert text in str(error), str(error)
        return
    raise AssertionError(f"accepted {body}")
