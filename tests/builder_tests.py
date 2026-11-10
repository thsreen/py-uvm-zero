"""Self-tests: TB_CONFIG: checking, building, routing, and class generation."""
from contextlib import redirect_stdout
import io
import sys

import cocotb

from importlib import import_module

from support import *  # noqa: F401,F403  shared helpers and fixtures


@cocotb.test()
async def json_builds_the_agent_hierarchy(dut):
    config = tb_json({"axi": {
        "aw": {"aw_port": port_file(), "monitor": True, "driver": True, "scoreboard": True},
        "r": {"r_port": port_file(), "monitor": True},
        "scoreboard": True, "stimulus": True}})
    env = TbEnv("env", dut, tb_config=config)
    axi = env.agents["axi"]
    aw, r = env.agents["axi"].agents["aw"], env.agents["axi"].agents["r"]
    assert isinstance(axi.scoreboards["scoreboard"], Scoreboard) and isinstance(axi.stimuli["stimulus"], Stimulus)
    assert isinstance(aw.monitors["monitor"], Monitor) and isinstance(aw.drivers["driver"], Driver)
    assert isinstance(aw.scoreboards["scoreboard"], Scoreboard) and not aw.stimuli
    assert not r.drivers and not r.scoreboards
    assert aw.interfaces["aw_port"].clk._path == dut.clk._path


@cocotb.test()
async def json_accepts_the_literal_placeholder_names(dut):
    config = tb_json({"agent": {"interface_def": {"interface_name": port_file(), "monitor": True}}})
    env = TbEnv("env", dut, tb_config=config)
    sub = env.agents["agent"].agents["interface_def"]
    assert "interface_name" in sub.interfaces


@cocotb.test()
async def json_flags_can_select_extended_classes(dut):
    config = tb_json({"agent": {"port": {"p": port_file(), "monitor": "AgentPortJsonMonitor"}}})
    env = TbEnv("env", dut, tb_config=config)
    assert type(env.agents["agent"].agents["port"].monitors["monitor"]).__name__ == "AgentPortJsonMonitor"


@cocotb.test()
async def config_naming_conventions_are_checked(dut):
    port = port_file()
    cases = [
        ({"Axi": {}}, "agent names are lower_snake_case"),
        ({"axi-1": {}}, "agent names are lower_snake_case"),
        ({"a": {"Port": port}}, "interface names are lower_snake_case"),
        ({"a": {"p": port, "driver": "awDriver"}}, "PascalCase"),
        ({"a": {"p": port, "driver": "AwThing"}}, "should end with Driver"),
        ({"a": {"p": port, "monitor": "AwDriver"}}, "should end with Monitor"),
        ({"axi": {"aw": {"p": port, "driver": "AwDriver"}}}, "should be named AxiAw<hints>Driver"),
        ({"axi": {"stimulus": "Axi"}}, "should be named Axi<hints><Name>"),
        ({"x": {"a_b": {"p": port, "monitor": "XABMonitor"}, "a": {"b": {"p": port, "monitor": "XABMonitor"}}}},
         "would share the file"),
        ({"x": {"scoreboard": "XScoreboard", "connections": ["XABPortMonitor -> XScoreboard", "XABBusMonitor -> XScoreboard"],
                "a_b": {"p": port, "monitor": "XABPortMonitor"}, "a": {"b": {"p": port, "monitor": "XABBusMonitor"}}}},
         "would share XScoreboard.on_a_b_monitor_callback"),
        ({"x": {"p": port, "monitor": "XMonitor", "scoreboard": "XScoreboard", "connections": ["XMonitor->XScoreboard"]}},
         "should be '<SourceClass> -> <TargetClass>'"),
        ({"x": {"p": port, "monitor": "XMonitor", "connections": ["XMonitor -> XBoardScoreboard"]}},
         "'XBoardScoreboard' in 'XMonitor -> XBoardScoreboard' is not a class of this agent or below"),
        ({"x": {"p": port, "monitor": True, "scoreboard": "XScoreboard", "connections": ["XMonitor -> XScoreboard"]}},
         "a true component has no class to name"),
        ({"x": {"p": port, "monitor": "XMonitor", "scoreboard": "XScoreboard",
                "connections": ["XMonitor -> XScoreboard", "XMonitor -> XScoreboard"]}}, "is listed twice"),
        ({"x": {"p": port, "monitor": "XMonitor", "connections": ["XMonitor -> XMonitor"]}}, "connects a class to itself"),
        ({"x": {"connections": "XMonitor -> XScoreboard"}}, "must be a list"),
        ({"x": {"p[2]": {"p": port, "monitor": "XPMonitor", "scoreboard": "XPScoreboard"},
                "connections": ["XPMonitor -> XPScoreboard"]}}, "XPScoreboard has 2 instances here"),
        ({"x": {"p": port, "driver": ["XPortDriver", "XBusDriver"]}}, "XBusDriver must name its interface"),
        ({"x": {"scoreboard": ["XDataScoreboard", "XScoreboard"]}}, "XScoreboard needs a hint"),
        ({"x": {"stimulus": ["XTraffic", "XTraffic"]}}, "more than one stimulus is named 'traffic'"),
        ({"x": {"stimulus": [], "p": port}}, "an empty list"),
        ({"simulation": {"tests": {"smoke": "XTraffic"}}, "x": {}}, "XTraffic is not a stimulus registered"),
        ({"simulation": {"tests": {"sim": "XTraffic"}}, "x": {"stimulus": "XTraffic"}}, "test names are lower_snake_case"),
        ({"simulation": {"tests": {"smoke": "XPTraffic"}}, "x": {"p[2]": {"stimulus": "XPTraffic"}}},
         "XPTraffic is registered by 2 agents"),
        ({"simulation": {"tests": ["XTraffic"]}}, "simulation.tests must map test names"),
        ({"x": {"p": write_json({"signals": [".clk", ".s_valid_i -> driver"]})}}, "would replace Transaction attributes"),
        ({"clock": {"period_ns": 10}}, "a signal such as dut.clock_i is required"),
        ({"clock": {"signal": "dut.clk", "period_ns": -1}}, "clock.period_ns must be a positive number"),
        ({"reset": {"signal": "dut.rst_n", "active_high": "no"}}, "reset.active_high must be true or false"),
        ({"reset": {"signal": "dut.rst_n", "width": 3}}, "reset: unknown settings ['width']"),
        ({"support": {}}, "would hide the existing Python module support"),
        ({"x": {"active": "no"}}, "x.active must be true or false"),
        ({"x": {"active": False, "p": port, "driver": True}}, "a passive agent (active: false) has no driver"),
        ({"x": {"active": False, "stimulus": "XTraffic"}}, "a passive agent (active: false) has no driver"),
        ({"clock": {"signal": "dut.clk", "check_period": True}}, "check_period applies only to a passive clock"),
        ({"clock": {"signal": "dut.clk", "active": False, "check_cycles": 9}}, "check_cycles requires check_period"),
        ({"settings": {"max_errors": 0}}, "settings.max_errors must be a positive integer"),
        ({"settings": {"timeout_unit": "days"}}, "settings.timeout_unit must be one of"),
        ({"settings": {"maxerrors": 2}}, "settings: unknown setting 'maxerrors'"),
        ({"settings": {"scoreboard": {"history": -1}}}, "settings.scoreboard.history must be"),
        ({"settings": {"scoreboard": {"inflight_timeout_cycles": 2.5}}}, "unknown setting 'inflight_timeout_cycles'"),
        ({"a": {"connected_module": ".u_{i}"}}, "only inside an array"),
        ({"a": {"port[2]": {}, "port_0": {}}}, "defined twice"),
        ({"a": {"reset": {}}}, "reserved"),
        ({"json": {}}, "would hide the existing Python module json"),
        ({"uvm_zero_base": {}}, "would hide the existing Python module uvm_zero_base"),
        ({"a": {"p": "does_not_exist.json"}}, "does_not_exist.json"),
    ]
    for body, text in cases:
        problems = config_problems(body)
        assert any(text in line for line in problems), (body, problems)


@cocotb.test()
async def config_reports_every_problem_at_once(dut):
    problems = config_problems({"Axi": {}, "ok": {"Port": port_file(), "scorebord": True,
                                                  "driver": "awDriver"}})
    assert len(problems) == 4, problems
    problems = config_problems({"Axi": {"aw": {"Port": "missing.json", "driver": "awDriver"}}})
    assert len(problems) == 4, problems


@cocotb.test()
async def generator_writes_one_file_per_class_by_the_naming_plan(dut):
    directory = generator_project()
    assert generate_main([str(directory / "tb.json")]) == 0
    expected = ["gen/agent/gen_left_driver.py", "gen/agent/gen_left_monitor.py",
                "gen/agent/gen_named_monitor.py", "gen/agent/gen_scoreboard.py",
                "gen/agent/gen_slave_monitor.py", "gen/agent/gen_span_driver.py", "gen/seqs/gen_traffic.py",
                "gen/agent/gen_left_port_txn.py", "gen/agent/gen_named_port_txn.py",
                "gen/agent/gen_slave_port_txn.py"]
    expected += ["gen/agent/infra/" + name + ".py" for name in
                 ("gen_agent", "gen_left_agent", "gen_named_agent", "gen_slave0_agent", "gen_slave1_agent")]
    expected.sort()
    found = sorted(str(path.relative_to(directory)) for path in directory.rglob("*.py"))
    assert found == expected, found
    for name in expected:
        compile((directory / name).read_text(), name, "exec")

    span = (directory / "gen/agent/gen_span_driver.py").read_text()
    assert "# self.interfaces['left.port']: signals valid" in span
    assert "# self.interfaces['slave_1.port']: signals valid" in span
    # Skeletons keep no local copies of interfaces, signals, or observed values.
    for name in expected:
        if "infra" not in name and "txn" not in name:
            code = [line for line in (directory / name).read_text().splitlines()
                    if " = " in line and not line.strip().startswith("#")]
            assert not code, (name, code)
    left = (directory / "gen/agent/gen_left_monitor.py").read_text()
    assert "self.interfaces['port'].values.valid == 1" in left and "def publish_port(self, txn: GenLeftPortTxn):" in left
    assert "self.publish_port(GenLeftPortTxn.from_values(self.interfaces['port'].values))" in left
    assert "from gen.agent.gen_left_port_txn import GenLeftPortTxn" in left
    assert "@dataclass\nclass GenSlavePortTxn(Transaction):\n    valid: object = None" in \
        (directory / "gen/agent/gen_slave_port_txn.py").read_text()
    assert "        self.drive_values(**GenLeftPortTxn.idle_values())" in (directory / "gen/agent/gen_left_driver.py").read_text()
    assert "        self.drive_values('named.port', **GenNamedPortTxn.idle_values())" in span
    assert "        return {'valid': 0}" in (directory / "gen/agent/gen_slave_port_txn.py").read_text()
    # One interface: typed with its Txn class. Several: untyped, since no single class fits.
    assert "async def drive(self, txn: GenLeftPortTxn):" in (directory / "gen/agent/gen_left_driver.py").read_text()
    assert "async def drive(self, txn):" in span
    # One interface: drive_values() needs no interface name. Several: the name picks one.
    assert "self.drive_values(**txn.signal_values())" in (directory / "gen/agent/gen_left_driver.py").read_text()
    assert "self.drive_values('named.port', **txn.signal_values())" in span
    assert "# self.interfaces['port']: signals id" in (directory / "gen/agent/gen_named_monitor.py").read_text()
    assert "uvm_zero_builder.generate" in span
    board = (directory / "gen/agent/gen_scoreboard.py").read_text()
    assert "def on_slave_monitor_callback(self, index_0, txn: GenSlavePortTxn):" in board
    assert "def on_left_monitor_callback(self, txn: GenLeftPortTxn):" in board
    traffic = (directory / "gen/seqs/gen_traffic.py").read_text()
    assert 'self.queue(GenLeftPortTxn(...), driver="left.driver")' in traffic


@cocotb.test()
async def generated_classes_build_and_route_scoreboard_callbacks(dut):
    import importlib
    import sys

    directory = generator_project()
    assert generate_main([str(directory / "tb.json")]) == 0
    sys.path.insert(0, str(directory))
    try:
        sys.modules.pop("gen.agent.gen_scoreboard", None)  # another test may have cached its own copy
        module = importlib.import_module("gen.agent.gen_scoreboard")
        seen = []
        module.GenScoreboard.on_slave_monitor_callback = lambda self, index_0, item: seen.append(("slave", index_0))
        module.GenScoreboard.on_left_monitor_callback = lambda self, item: seen.append(("left", None))
        module.GenScoreboard.on_named_monitor_callback = lambda self, item: seen.append(("named", None))
        env = TbEnv("env", dut, tb_config=directory / "tb.json")
    finally:
        sys.path.remove(str(directory))

    board = env.agents["gen"].scoreboards["scoreboard"]
    env._phase("connect")
    for child in ("slave_1", "left", "slave_0"):
        env.agents["gen"].agents[child].monitors["monitor"].publish(Transaction(1))
    board.callback(Transaction(1, source="env.gen.reset.monitor"))
    assert seen == [("slave", 1), ("left", None), ("slave", 0)]

    driver = env.agents["gen"].drivers["driver"]
    assert sorted(driver.interfaces) == ["left.port", "named.port", "slave_0.port", "slave_1.port"]
    try:
        await driver.drive(Transaction(1))
    except NotImplementedError as error:
        assert "GenSpanDriver.drive" in str(error)
    else:
        raise AssertionError("the skeleton did not ask for an implementation")


@cocotb.test()
async def generator_never_overwrites_and_check_writes_nothing(dut):
    directory = generator_project()
    assert generate_main([str(directory / "tb.json"), "--check"]) == 0
    assert not list(directory.rglob("*.py"))

    assert generate_main([str(directory / "tb.json")]) == 0
    edited = directory / "gen/agent/gen_left_driver.py"
    edited.write_text("# my implementation\n")
    assert generate_main([str(directory / "tb.json")]) == 0
    assert edited.read_text() == "# my implementation\n"


@cocotb.test()
async def generated_testbench_carries_a_transaction_end_to_end(dut):
    """JSON -> generate -> fill in the blanks -> stimulus, handler, driver, DUT, monitor, scoreboard."""
    import importlib
    import sys

    directory = Path(tempfile.mkdtemp())
    (directory / "pipe_in.json").write_text(json.dumps(
        {"signals": [".clk [Clock]", ".s_valid_i -> valid", ".s_data_i -> data"]}))
    (directory / "pipe_out.json").write_text(json.dumps(
        {"signals": [".clk [Clock]", ".m_valid_o -> valid", ".m_data_o -> data"]}))
    (directory / "tb.json").write_text(json.dumps({"simulation": {"tests": {"main": "PipeTraffic"}}, "pipe": {
        "connected_module": "dut", "scoreboard": "PipeCheckScoreboard", "stimulus": "PipeTraffic",
        "connections": ["PipeOutMonitor -> PipeCheckScoreboard"],
        "inp": {"port": "pipe_in.json", "driver": "PipeInpDriver"},
        "out": {"port": "pipe_out.json", "monitor": "PipeOutMonitor"}}}))
    assert generate_main([str(directory / "tb.json")]) == 0

    triggers = "from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge\n"
    fill(directory / "pipe/seqs/pipe_traffic.py", {
        'raise NotImplementedError("PipeTraffic.run: generate the scenario")':
            "for value in (5, 9):\n            self.queue(PipeInpPortTxn(data=value), driver=\"inp.driver\")\n"
            "        await self.wait_idle()"})
    fill(directory / "pipe/agent/pipe_inp_driver.py", {
        'raise NotImplementedError("PipeInpDriver.drive: drive the transaction onto the signals")':
            "await FallingEdge(self.interfaces['port'].clk)\n"
            "        self.drive_values('port', valid=1, data=txn.data)\n"
            "        await FallingEdge(self.interfaces['port'].clk)\n"
            "        self.drive_values('port', valid=0)"}, triggers)
    fill(directory / "pipe/agent/pipe_out_monitor.py", {
        'raise NotImplementedError("PipeOutMonitor.run: observe transfers and publish them")':
            "while True:\n            await RisingEdge(self.interfaces['port'].clk)\n            await ReadOnly()\n"
            "            if str(self.interfaces['port'].valid.value) == \"1\":\n"
            "                self.publish(PipeOutPortTxn(data=int(self.interfaces['port'].data.value)))"},
         triggers)
    fill(directory / "pipe/agent/pipe_check_scoreboard.py", {
        "# Add only the queues, reference model and checks this protocol requires.":
            "self.received = []",
        'raise NotImplementedError("PipeCheckScoreboard.on_out_monitor_callback: check this transaction")':
            "self.received.append(txn.data)"})

    start_clock(dut)
    dut.s_valid_i.value = 0
    await ClockCycles(dut.clk, 5)  # flush items earlier tests left in the DUT's pipeline
    env = TbEnv("env", dut, tb_config=directory / "tb.json", heartbeat_clock=dut.clk)
    assert await failure_of(env) is None

    assert env.agents["pipe"].scoreboards["scoreboard"].received == [5, 9] and env.test == "main"
    assert env.agents["pipe"].agents["inp"].handler.drivers["driver"] is \
        env.agents["pipe"].agents["inp"].drivers["driver"]


@cocotb.test()
async def scoreboard_routes_follow_json_changes(dut):
    """Refresh explicit infrastructure after JSON changes; preserve user callbacks."""
    directory = generator_project()
    config_path = directory / "tb.json"
    assert generate_main([str(config_path)]) == 0
    config = json.loads(config_path.read_text())
    config["gen"]["extra"] = {"connected_module": ".b", "port": "port.json", "monitor": "GenExtraMonitor"}
    config["gen"]["connections"].append("GenExtraMonitor -> GenScoreboard")
    config_path.write_text(json.dumps(config))
    output = io.StringIO()
    with redirect_stdout(output):
        assert generate_main([str(config_path), "--refresh-infra"]) == 0
    assert 'add def on_extra_monitor_callback(...) for "GenExtraMonitor -> GenScoreboard"' in output.getvalue()

    env = TbEnv("env", dut, tb_config=config_path)
    try:
        env._phase("connect")
    except AttributeError as error:
        assert "on_extra_monitor_callback" in str(error)
    else:
        raise AssertionError("the missing callback was not reported")

    module = import_module("gen.agent.gen_scoreboard")
    seen = []
    module.GenScoreboard.on_extra_monitor_callback = lambda self, item: seen.append(item.data)
    env = TbEnv("env", dut, tb_config=config_path)
    env._phase("connect")
    env.agents["gen"].agents["extra"].monitors["monitor"].publish(Transaction("new"))
    assert seen == ["new"]


@cocotb.test()
async def an_agent_registers_several_stimuli_and_a_test_picks_one(dut):
    config = tb_json({"simulation": {"tests": {"first": "AgentJsonStimulus", "second": "AgentSecondStimulus"}},
                      "agent": {"stimulus": ["AgentJsonStimulus", "AgentSecondStimulus"]}})
    JsonStimulus.runs.clear()
    env = TbEnv("env", dut, tb_config=config, test="second")
    agent = env.agents["agent"]
    assert sorted(agent.stimuli) == ["json_stimulus", "second_stimulus"]
    assert env.test == "second" and env.stimulus is agent.stimuli["second_stimulus"]
    assert await failure_of(env) is None
    # Building may reload the fixture module, so read the class that actually ran.
    assert type(env.stimulus).runs == ["env.agent.second_stimulus"]

    # The first test is the default; an unknown test is an error.
    assert TbEnv("env", dut, tb_config=config).test == "first"
    try:
        TbEnv("env", dut, tb_config=config, test="third")
    except ValueError as error:
        assert "unknown test 'third'" in str(error)
    else:
        raise AssertionError("an unknown test was accepted")

    # TB_SEQUENCE_CONFIG overrides settings the stimulus defines; with TB_CONFIG,
    # TB_SEQUENCE is refused because only registered stimuli may run.
    env = TbEnv("env", dut, tb_config=config, sequence_config={"runs": ["replaced"]})
    assert env.stimulus.runs == ["replaced"]
    saved = dict(os.environ)
    os.environ.update({"TB_ENV": "uvm_zero_base:TbEnv", "TB_CONFIG": config, "TB_SEQUENCE": "x:Y"})
    try:
        TestConfig.from_environment()
    except ValueError as error:
        assert "TB_TEST" in str(error)
    else:
        raise AssertionError("TB_SEQUENCE was accepted with TB_CONFIG")
    finally:
        os.environ.clear()
        os.environ.update(saved)


@cocotb.test()
async def a_test_stimulus_restarts_on_reset_only_when_asked(dut):
    """Its agent's reset never stops a test's stimulus; restart_sequence restarts it."""
    for restart in (False, True):
        runs, finished = [], []

        class Traffic(Stimulus):
            async def run(self):
                runs.append(get_sim_time(unit="ns"))
                await Timer(200, unit="ns")
                finished.append(True)

        env = reset_env(dut, None)
        env.a = RecordingAgent("a", env, stimulus_types={"stimulus": Traffic},
                               interface=Interface(dut, clk="clk"), **domain_settings(dut))
        env.stimulus = env.a.stimuli["stimulus"]
        env.reset_handler = env.reset.handler
        env.reset_handler.restart_sequence = restart

        async def pulse_later():
            await Timer(100, unit="ns")
            await env.reset.pulse(duration_factor=1)

        cocotb.start_soon(pulse_later())
        assert await failure_of(env) is None
        assert finished == [True] and len(runs) == (2 if restart else 1), (restart, runs)


@cocotb.test()
async def a_test_stimulus_may_reset_its_own_agent(dut):
    finished = []

    class PulsesItself(Stimulus):
        async def run(self):
            await self.env.reset.wait_released()
            await self.env.reset.pulse(duration_factor=1)
            await Timer(20, unit="ns")
            finished.append(True)

    config = tb_json({"clock": {"signal": "dut.clk"}, "reset": {"signal": "dut.rst_n", "active_high": False}})
    env = TbEnv("env", dut, tb_config=config)
    agent = Agent("agent", env, stimulus_types={"pulses": PulsesItself}, **domain_settings(dut))
    env.stimulus = agent.stimuli["pulses"]
    assert await failure_of(env) is None and finished == [True]
    # The JSON clock and reset interfaces are tagged, so values never track the clock.
    assert list(env.clock.interfaces["clock"].clocks) == ["clk"]
    assert list(env.reset.interfaces["reset"].resets) == ["reset"]
    assert "clk" not in env.clock.interfaces["clock"].values


@cocotb.test()
async def scoreboard_routes_by_the_delivering_monitor(dut):
    checked = []

    class Board(Scoreboard):
        def on_bus(self, transaction):
            checked.append(transaction.data)

    class RepublishesAnItem(Monitor):
        async def run(self):
            self.publish(Transaction(7, source="env.agent.driver_handler"))

    class Wait(Stimulus):
        async def run(self):
            await Timer(5, unit="ns")

    env = TbEnv("env", dut, drain_cycles=0, sequence_type=Wait)
    agent = Agent("agent", env, monitor_types={"monitor": RepublishesAnItem}, scoreboard_types={"scoreboard": Board},
                  interface=Interface(dut, clk="clk"))
    agent.monitors["monitor"].bind_interface(agent.interfaces["default"])
    board = agent.scoreboards["scoreboard"]
    board.subscribe(agent.monitors["monitor"], board.on_bus, interface="default")
    assert await failure_of(env) is None
    assert checked == [7]


@cocotb.test()
async def json_alone_runs_a_testbench_with_clock_and_reset(dut):
    """No env class: the JSON gives the clock, reset, agents, and classes."""
    directory = Path(tempfile.mkdtemp())
    (directory / "pipe_in.json").write_text(json.dumps(
        {"signals": [".clk [Clock]", ".s_valid_i -> valid", ".s_data_i -> data"]}))
    (directory / "pipe_out.json").write_text(json.dumps(
        {"signals": [".clk [Clock]", ".m_valid_o -> valid", ".m_data_o -> data"]}))
    (directory / "tb.json").write_text(json.dumps({
        "clock": {"signal": "dut.clk", "period_ns": 10},
        "reset": {"signal": "dut.rst_n", "active_high": False, "duration_factor": 5},
        "simulation": {"tests": {"main": "SoloTraffic"}},
        "solo": {"scoreboard": "SoloScoreboard", "stimulus": "SoloTraffic", "connections": ["SoloOutMonitor -> SoloScoreboard"],
                 "inp": {"port": "pipe_in.json", "driver": "SoloInpDriver"},
                 "out": {"port": "pipe_out.json", "monitor": "SoloOutMonitor"}}}))
    assert generate_main([str(directory / "tb.json")]) == 0

    triggers = "from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge\n"
    fill(directory / "solo/seqs/solo_traffic.py", {
        'raise NotImplementedError("SoloTraffic.run: generate the scenario")':
            "for value in (5, 9):\n            self.queue(SoloInpPortTxn(valid=1, data=value), driver=\"inp.driver\")\n"
            "        await self.wait_idle()"})
    fill(directory / "solo/agent/solo_inp_driver.py", {
        'raise NotImplementedError("SoloInpDriver.drive: drive the transaction onto the signals")':
            "await FallingEdge(self.interfaces['port'].clk)\n"
            "        self.drive_values('port', **txn.signal_values())\n"
            "        await FallingEdge(self.interfaces['port'].clk)\n"
            "        self.drive_values('port', valid=0)"}, triggers)
    fill(directory / "solo/agent/solo_out_monitor.py", {
        'raise NotImplementedError("SoloOutMonitor.run: observe transfers and publish them")':
            # Sample at the clock edge from the interface's observed values.
            "while True:\n            await RisingEdge(self.interfaces['port'].clk)\n"
            "            if self.interfaces['port'].values.valid == 1:\n"
            "                self.publish_port(SoloOutPortTxn.from_values(self.interfaces['port'].values))"},
         triggers)
    fill(directory / "solo/agent/solo_scoreboard.py", {
        "# Add only the queues, reference model and checks this protocol requires.":
            "self.received = []",
        'raise NotImplementedError("SoloScoreboard.on_out_monitor_callback: check this transaction")':
            "self.received.append(int(txn.data))"})

    dut.s_valid_i.value = 0
    env = TbEnv("env", dut, tb_config=directory / "tb.json")
    assert isinstance(env.agents["solo"].agents["reset"], ResetAgent)
    assert env.reset_handler is env.reset.handler
    assert await failure_of(env) is None
    assert env.agents["solo"].scoreboards["scoreboard"].received == [5, 9]


@cocotb.test()
async def generator_lists_files_no_class_names_any_more(dut):
    import contextlib
    import io

    directory = generator_project()
    assert generate_main([str(directory / "tb.json")]) == 0
    (directory / "gen/agent/gen_old_monitor.py").write_text("# renamed away\n")
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        assert generate_main([str(directory / "tb.json"), "--check"]) == 0
    assert "unused" in output.getvalue() and "gen_old_monitor.py" in output.getvalue()


@cocotb.test()
async def generator_rejects_a_bad_config_without_writing(dut):
    import contextlib
    import io

    directory = Path(tempfile.mkdtemp())
    (directory / "tb.json").write_text(json.dumps({"Axi": {"driver": "awDriver"}}))
    errors = io.StringIO()
    with contextlib.redirect_stderr(errors):
        assert generate_main([str(directory / "tb.json")]) == 1
    assert "lower_snake_case" in errors.getvalue() and not list(directory.rglob("*.py"))


@cocotb.test()
async def naming_plan_maps_hierarchy_and_class_to_a_module(dut):
    assert module_for("driver", ("axi", "aw"), "AxiAwDriver") == "axi.agent.axi_aw_driver"
    assert module_for("monitor", ("axi", "slave"), "AxiSlaveBurstMonitor") == "axi.agent.axi_slave_burst_monitor"
    assert module_for("stimulus", ("axi",), "AxiTraffic") == "axi.seqs.axi_traffic"


@cocotb.test()
async def array_instances_share_one_class_location(dut):
    env = TbEnv("env", dut, tb_config=tb_json({"agent": {"slave[2]": {
        "f": port_file(), "monitor": "AgentSlaveJsonMonitor"}}}))
    for index in range(2):
        assert type(env.agents["agent"].agents[f"slave_{index}"].monitors["monitor"]).__name__ == "AgentSlaveJsonMonitor"


@cocotb.test()
async def missing_import_inside_a_user_module_is_not_hidden(dut):
    try:
        TbEnv("env", dut, tb_config=tb_json({"a": {"p": {"f": port_file(), "monitor": "APBrokenMonitor"}}}))
    except ModuleNotFoundError as error:
        assert error.name == "module_that_does_not_exist"
        return
    raise AssertionError("the import failure was hidden")


@cocotb.test()
async def json_built_monitors_feed_their_own_and_the_agent_scoreboard(dut):
    config = tb_json({"agent": {
        "a": {"p": port_file(), "monitor": "AgentAMonitor", "scoreboard": "AgentAScoreboard",
              "connections": ["AgentAMonitor -> AgentAScoreboard"]},
        "b": {"p": port_file(), "monitor": "AgentBMonitor"},
        "scoreboard": "AgentScoreboard",
        "connections": ["AgentAMonitor -> AgentScoreboard", "AgentBMonitor -> AgentScoreboard"]}})

    class Publishes(Stimulus):
        async def run(self):
            for port in ("a", "b"):
                self.env.agents["agent"].agents[port].monitors["monitor"].publish(Transaction(port))

    env = TbEnv("env", dut, sequence_type=Publishes, tb_config=config, drain_cycles=0, scoreboard={"history": 10})
    assert await failure_of(env) is None
    assert [item.data for item in env.agents["agent"].scoreboards["scoreboard"].transactions] == ["a", "b"]
    assert [item.data for item in env.agents["agent"].agents["a"].scoreboards["scoreboard"].transactions] == ["a"]


@cocotb.test()
async def registered_stimuli_run_only_when_a_test_names_them(dut):
    JsonStimulus.runs.clear()
    config = tb_json({"simulation": {"tests": {"main": "AgentJsonStimulus"}}, "agent": {
        "port": {"p": port_file(), "stimulus": "AgentPortJsonStimulus"},
        "stimulus": "AgentJsonStimulus"}})
    env = TbEnv("env", dut, tb_config=config)
    child = env.agents["agent"].agents["port"]
    assert isinstance(child.stimuli["json_stimulus"], Stimulus)
    assert await failure_of(env) is None
    assert type(env.stimulus).runs == ["env.agent.json_stimulus"]


@cocotb.test()
async def json_module_is_inherited_and_recorded(dut):
    env = TbEnv("env", dut, tb_config=tb_json({"top": {
        "connected_module": "dut.a", "p": {"f": valid_file(), "monitor": True}}}))
    interface, node = monitored_interface(env, "top", "p")
    assert interface.valid._path == dut.a.valid._path
    assert node.connected_module == "dut.a" and env.agents["top"].connected_module == "dut.a"


@cocotb.test()
async def json_relative_module_extends_the_parent(dut):
    env = TbEnv("env", dut, tb_config=tb_json({"top": {
        "p": {"connected_module": ".b", "f": valid_file(), "monitor": True}}}))
    interface, node = monitored_interface(env, "top", "p")
    assert interface.valid._path == dut.b.valid._path and node.connected_module == "dut.b"


@cocotb.test()
async def json_absolute_module_replaces_the_parent(dut):
    env = TbEnv("env", dut, tb_config=tb_json({"top": {
        "connected_module": "dut.a",
        "p": {"connected_module": "dut.b", "f": valid_file(), "monitor": True}}}))
    assert monitored_interface(env, "top", "p")[0].valid._path == dut.b.valid._path


@cocotb.test()
async def json_module_wins_over_an_absolute_one_in_the_interface_file(dut):
    file = write_json({"signals": [".valid"], "connected_module": "dut.b"})
    env = TbEnv("env", dut, tb_config=tb_json({"top": {
        "connected_module": "dut.a", "p": {"f": file, "monitor": True}}}))
    assert monitored_interface(env, "top", "p")[0].valid._path == dut.a.valid._path


@cocotb.test()
async def json_agents_nest_to_any_depth(dut):
    env = TbEnv("env", dut, tb_config=tb_json({"l1": {"connected_module": "dut", "l2": {"l3": {
        "connected_module": ".gen_blk[1].u", "f": valid_file(), "monitor": True, "scoreboard": True}}}}))
    interface, node = monitored_interface(env, "l1", "l2", "l3")
    assert interface.valid._path == dut.gen_blk[1].u.valid._path
    assert node.path == "env.l1.l2.l3"


@cocotb.test()
async def json_arrays_create_one_agent_per_instance(dut):
    env = TbEnv("env", dut, tb_config=tb_json({"top": {"port[2]": {
        "connected_module": ".gen_blk[{i}].u", "f": valid_file(), "monitor": True}}}))
    for index in range(2):
        interface, node = monitored_interface(env, "top", f"port_{index}")
        assert interface.valid._path == dut.gen_blk[index].u.valid._path
        assert node.connected_module == f"dut.gen_blk[{index}].u"


@cocotb.test()
async def json_top_level_keys_can_be_arrays(dut):
    env = TbEnv("env", dut, tb_config=tb_json({"cluster[3]": {"scoreboard": True}}))
    assert sorted(env.agents) == ["cluster_0", "cluster_1", "cluster_2"]


@cocotb.test()
async def json_component_gets_every_interface_in_its_object(dut):
    env = TbEnv("env", dut, tb_config=tb_json({"top": {
        "connected_module": "dut.a", "first": valid_file(), "second": valid_file(),
        "monitor": True, "driver": True}}))
    top = env.agents["top"]
    for component in (top.monitors["monitor"], top.drivers["driver"]):
        assert sorted(component.interfaces) == ["first", "second"]
        assert component.interface is None
    assert top.monitors["monitor"].interfaces["first"].valid._path == dut.a.valid._path


@cocotb.test()
async def json_parent_component_spans_its_child_agents(dut):
    env = TbEnv("env", dut, tb_config=tb_json({"top": {
        "monitor": True, "driver": True,
        "left": {"connected_module": ".a", "port": valid_file(), "monitor": True, "driver": True},
        "right": {"connected_module": ".b", "port": valid_file(), "monitor": True, "driver": True}}}))
    top = env.agents["top"]
    monitor = top.monitors["monitor"]
    assert sorted(monitor.interfaces) == ["left.port", "right.port"]
    assert monitor.interfaces["left.port"].valid._path == dut.a.valid._path
    assert monitor.interfaces["right.port"].valid._path == dut.b.valid._path
    assert top.agents["left"].monitors["monitor"].interface.valid._path == dut.a.valid._path
    assert sorted(subtree(top, "drivers")) == ["driver", "left.driver", "right.driver"]
    assert sorted(subtree(top, "monitors")) == ["left.monitor", "monitor", "right.monitor"]


@cocotb.test()
async def json_spanning_component_covers_arrays_and_nesting(dut):
    env = TbEnv("env", dut, tb_config=tb_json({"top": {"monitor": True, "group": {"port[2]": {
        "connected_module": ".gen_blk[{i}].u", "p": valid_file()}}}}))
    monitor = env.agents["top"].monitors["monitor"]
    assert sorted(monitor.interfaces) == ["group.port_0.p", "group.port_1.p"]
    assert monitor.interfaces["group.port_1.p"].valid._path == dut.gen_blk[1].u.valid._path


@cocotb.test()
async def json_alone_builds_a_working_spanning_driver(dut):
    SpanningDriver.driven.clear()
    SpanChildDriver.driven.clear()
    env = TbEnv("env", dut, tb_config=tb_json({"simulation": {"tests": {"main": "TopSpanSends"}}, "top": {
        "driver": "TopSpanningDriver",
        "stimulus": "TopSpanSends",
        "left": {"connected_module": ".a", "port": valid_file(),
                 "driver": "TopLeftSpanChildDriver"},
        "right": {"connected_module": ".b", "port": valid_file()}}}))
    assert await failure_of(env) is None
    assert type(env.agents["top"].drivers["driver"]).driven == [["left.port", "right.port"]]
    assert type(env.agents["top"].agents["left"].drivers["driver"]).driven == ["child"]


@cocotb.test()
async def json_alone_connects_a_spanning_monitor_to_its_scoreboard(dut):
    env = TbEnv("env", dut, drain_cycles=0, scoreboard={"history": 10}, tb_config=tb_json({
        "simulation": {"tests": {"main": "TopSpanPublishes"}}, "top": {
        "monitor": "TopMonitor", "scoreboard": "TopScoreboard", "stimulus": "TopSpanPublishes",
        "connections": ["TopMonitor -> TopScoreboard"],
        "left": {"connected_module": ".a", "port": valid_file()}}}))
    assert await failure_of(env) is None
    assert [item.data for item in env.agents["top"].scoreboards["scoreboard"].transactions] == ["span"]


@cocotb.test()
async def run_without_any_stimulus_is_an_error(dut):
    assert isinstance(await failure_of(TbEnv("env", dut)), NotImplementedError)


@cocotb.test()
async def json_built_agents_get_their_reset_uvc(dut):
    def agent_reset(name, parent):
        return passive_reset(name, parent, interface=Interface(parent.root.dut, rst_n="rst_n"))

    class Env(TbEnv):
        agent_reset_type = staticmethod(agent_reset)

    env = Env("env", dut, tb_config=tb_json({"a": {"p": {"f": port_file(), "monitor": True}}}))
    assert isinstance(env.agents["a"].agents["reset"], ResetAgent)


@cocotb.test()
async def json_description_errors_are_reported(dut):
    cases = [
        ({"a": {"p": {"monitor": True}}}, ValueError, "needs an interface"),
        ({"a": {"p": {"f": port_file(), "scorebord": True}}}, ValueError, "unknown settings"),
        ({"a": "not an object"}, ValueError, "JSON object"),
        ({"a": {"p": {"f": port_file(), "monitor": 1}}}, ValueError, "class name"),
        ({"a": {"p": {"f": port_file(), "monitor": "pkg.mod:Thing"}}}, ValueError, "class name"),
        ({"a": {"p": {"f": port_file(), "monitor": "APMissingMonitor"}}}, ModuleNotFoundError,
         "a.agent.ap_missing_monitor"),
        ({"a": {"p": {"f": port_file(), "monitor": "APNotAMonitor"}}}, TypeError, "Monitor"),
    ]
    for body, kind, text in cases:
        try:
            TbEnv("env", dut, tb_config=tb_json(body))
        except kind as error:
            assert text in str(error), error
            continue
        raise AssertionError(f"accepted {body}")


@cocotb.test()
async def tb_config_is_selected_from_the_environment(dut):
    config = tb_json({"agent": {"p": {"f": port_file(), "monitor": True}}})
    saved = dict(os.environ)
    os.environ.update({"TB_ENV": "uvm_zero_base:TbEnv", "TB_CONFIG": config})
    os.environ.pop("TB_ENV_CONFIG", None)
    try:
        env = TestConfig.from_environment().create_env(dut)
    finally:
        os.environ.clear()
        os.environ.update(saved)
    assert "agent" in env.agents


# Settings: Python defaults, then TB_CONFIG "settings", then TB_ENV_CONFIG

@cocotb.test()
async def python_defaults_apply_without_any_config(dut):
    env = TbEnv("env", dut)
    assert (env.max_errors, env.timeout, env.timeout_unit, env.heartbeat_timeout, env.drain_cycles) == \
        (1, 1, "ms", 1000, 10)
    assert Scoreboard("board", env).transactions.maxlen == 0


@cocotb.test()
async def tb_config_settings_replace_python_defaults(dut):
    config = tb_json({"settings": {"max_errors": 3, "timeout": 5, "timeout_unit": "us", "drain_cycles": 0,
                                   "scoreboard": {"history": 7}},
                      "agent": {"scoreboard": True}})
    env = TbEnv("env", dut, tb_config=config)
    assert (env.max_errors, env.timeout, env.timeout_unit, env.heartbeat_timeout, env.drain_cycles) == \
        (3, 5, "us", 1000, 0)
    board = env.agents["agent"].scoreboards["scoreboard"]
    assert board.transactions.maxlen == 7
    # Python-built scoreboards under the same env take the same defaults.
    assert Scoreboard("extra", env).transactions.maxlen == 7


@cocotb.test()
async def tb_env_config_replaces_both(dut):
    config = tb_json({"settings": {"max_errors": 3, "timeout": 5, "scoreboard": {"history": 7}},
                      "agent": {"scoreboard": True}})
    env = TbEnv("env", dut, tb_config=config, max_errors=9, timeout=None, scoreboard={"history": 2})
    assert (env.max_errors, env.timeout) == (9, None)
    assert env.agents["agent"].scoreboards["scoreboard"].transactions.maxlen == 2

    env = TbEnv("env", dut, drain_cycles=4, scoreboard={"history": 30})
    assert env.drain_cycles == 4 and Scoreboard("board", env).transactions.maxlen == 30


@cocotb.test()
async def explicit_scoreboard_arguments_still_win(dut):
    env = TbEnv("env", dut, scoreboard={"history": 2})
    assert Scoreboard("board", env, history=5).transactions.maxlen == 5


@cocotb.test()
async def tb_env_config_file_reaches_every_layer(dut):
    config = tb_json({"settings": {"max_errors": 3}, "clock": {"signal": "dut.clk", "period_ns": 10},
                      "agent": {"scoreboard": True}})
    overrides = write_json({"max_errors": 6, "scoreboard": {"history": 4}, "clock": {"period_ns": 20}})
    saved = dict(os.environ)
    os.environ.update({"TB_ENV": "uvm_zero_base:TbEnv", "TB_CONFIG": config, "TB_ENV_CONFIG": overrides})
    try:
        env = TestConfig.from_environment().create_env(dut)
    finally:
        os.environ.clear()
        os.environ.update(saved)
    assert env.max_errors == 6
    assert env.agents["agent"].scoreboards["scoreboard"].transactions.maxlen == 4
    assert env.clock.drivers["driver"].period_ns == 20


@cocotb.test()
async def bad_overrides_are_reported(dut):
    for kwargs, text in (({"max_errors": 0}, "max_errors must be a positive integer"),
                         ({"scoreboard": {"histroy": 3}}, "unknown setting 'histroy'"),
                         ({"clock": {"period_ns": 20}}, "need a TB_CONFIG")):
        try:
            TbEnv("env", dut, **kwargs)
        except ValueError as error:
            assert text in str(error), error
            continue
        raise AssertionError(f"accepted {kwargs}")


@cocotb.test()
async def json_clock_can_be_passive_and_checked(dut):
    start_clock(dut)
    config = tb_json({"clock": {"signal": "dut.clk", "period_ns": 10, "active": False,
                                "check_period": True, "check_cycles": 5}})

    class Waits(Stimulus):
        async def run(self):
            await ClockCycles(self.env.dut.clk, 20)

    env = TbEnv("env", dut, tb_config=config, sequence_type=Waits)
    assert not env.clock.drivers and env.clock.monitors["monitor"].check_cycles == 5
    assert await failure_of(env) is None
    assert env.clock.monitors["monitor"].windows >= 2


@cocotb.test()
async def json_agent_can_be_passive(dut):
    env = TbEnv("env", dut, tb_config=tb_json({"watch": {"active": False, "p": port_file(), "monitor": True,
                                                          "scoreboard": True}}))
    watch = env.agents["watch"]
    assert watch.active is False and not watch.drivers and isinstance(watch.handler, Handler)
    assert isinstance(watch.monitors["monitor"], Monitor)


@cocotb.test()
async def nested_arrays_each_replace_their_own_index(dut):
    plan = load_plan(tb_json({"outer[2]": {"connected_module": ".outer[{i}]",
                                           "inner[2]": {"connected_module": ".inner[{i}]"}}}))
    modules = {f"{outer.name}.{inner.name}": inner.connected_module
               for outer in plan.agents for inner in outer.children}
    assert modules == {"outer_0.inner_0": "dut.outer[0].inner[0]", "outer_0.inner_1": "dut.outer[0].inner[1]",
                       "outer_1.inner_0": "dut.outer[1].inner[0]", "outer_1.inner_1": "dut.outer[1].inner[1]"}


@cocotb.test()
async def each_config_directory_loads_its_own_classes(dut):
    def project(marker):
        directory = Path(tempfile.mkdtemp())
        (directory / "port.json").write_text(json.dumps({"signals": [".clk"]}))
        (directory / "dup" / "agent").mkdir(parents=True)
        (directory / "dup" / "agent" / "dup_marker_monitor.py").write_text(
            f"from uvm_zero_base import Monitor\n\n\nclass DupMarkerMonitor(Monitor):\n    MARK = {marker}\n")
        (directory / "tb.json").write_text(json.dumps({"dup": {"p": "port.json", "monitor": "DupMarkerMonitor"}}))
        return materialize_infra(directory / "tb.json")

    first, second = project(1), project(2)
    marks = [TbEnv("env", dut, tb_config=config).agents["dup"].monitors["monitor"].MARK
             for config in (first, second, first)]
    assert marks == [1, 2, 1]


@cocotb.test()
async def python_keywords_are_rejected_as_signal_names(dut):
    problems = config_problems({"a": {"p": write_json({"signals": [".clk -> class"]}), "monitor": True}})
    assert any("is a Python keyword" in line for line in problems), problems
    try:
        Interface(dut, **{"class": "clk"})
    except ValueError:
        return
    raise AssertionError("a keyword was accepted as a signal name")


@cocotb.test()
async def a_package_inside_the_config_directory_is_not_a_clash(dut):
    directory = Path(tempfile.mkdtemp())
    (directory / "port.json").write_text(json.dumps({"signals": [".clk"]}))
    (directory / "owntb" / "agent").mkdir(parents=True)
    (directory / "owntb" / "__init__.py").write_text("")
    (directory / "tb.json").write_text(json.dumps({"owntb": {"p": "port.json", "monitor": True}}))
    sys.path.insert(0, str(directory))
    try:
        assert [node.name for node in load_plan(directory / "tb.json").agents] == ["owntb"]
    finally:
        sys.path.remove(str(directory))


@cocotb.test()
async def interface_config_needs_an_env_that_takes_it(dut):
    saved = dict(os.environ)
    os.environ.update({"TB_ENV": "uvm_zero_base:TbEnv", "TB_INTERFACE_CONFIG": port_file()})
    os.environ.pop("TB_ENV_CONFIG", None)
    os.environ.pop("TB_CONFIG", None)
    try:
        TestConfig.from_environment()
    except ValueError as error:
        assert "takes no interface_config" in str(error)
        return
    finally:
        os.environ.clear()
        os.environ.update(saved)
    raise AssertionError("TB_INTERFACE_CONFIG was accepted by an env without interface_config")


@cocotb.test()
async def each_config_directory_loads_its_own_helper_modules(dut):
    def project(marker):
        directory = Path(tempfile.mkdtemp())
        (directory / "port.json").write_text(json.dumps({"signals": [".clk"]}))
        package = directory / "helped" / "agent"
        package.mkdir(parents=True)
        (package / "helped_constants.py").write_text(f"MARK = {marker}\n")
        (package / "helped_marker_monitor.py").write_text(
            "from uvm_zero_base import Monitor\nfrom helped.agent.helped_constants import MARK\n\n\n"
            "class HelpedMarkerMonitor(Monitor):\n    def mark(self):\n        return MARK\n")
        (directory / "tb.json").write_text(json.dumps({"helped": {"p": "port.json", "monitor": "HelpedMarkerMonitor"}}))
        return materialize_infra(directory / "tb.json")

    first, second = project(1), project(2)
    marks = [TbEnv("env", dut, tb_config=config).agents["helped"].monitors["monitor"].mark()
             for config in (first, second, first)]
    assert marks == [1, 2, 1]


@cocotb.test()
async def generated_agent_code_is_plain_and_imports_what_it_uses(dut):
    directory = Path(tempfile.mkdtemp())
    (directory / "port.json").write_text(json.dumps({"signals": [".clk"]}))
    (directory / "tb.json").write_text(json.dumps({"plain": {
        "stimulus": "PlainTraffic", "scoreboard": True,
        "inner": {"port": "port.json", "monitor": True, "stimulus": "PlainInnerTraffic"}}}))
    assert generate_main([str(directory / "tb.json")]) == 0
    infra = directory / "plain" / "agent" / "infra"
    top = (infra / "plain_agent.py").read_text()
    inner = (infra / "plain_inner_agent.py").read_text()
    assert "from uvm_zero_base import Agent, Scoreboard\n" in top and "        interfaces = {}\n" in top, top
    assert "            stimulus_types={'traffic': PlainTraffic},\n" in top and "def connect_callbacks(self):" in top
    assert "from uvm_zero_base import Agent, Interface, Monitor\n" in inner, inner
    assert "            stimulus_types={'traffic': PlainInnerTraffic},\n" in inner
    assert "auto_connect" not in top + inner


def monitor_list_project(monitors):
    directory = Path(tempfile.mkdtemp())
    for name in ("input", "output"):
        (directory / f"{name}.json").write_text(json.dumps({"signals": [".clk"]}))
    (directory / "tb.json").write_text(json.dumps({"mat_mul": {
        "input": "input.json", "output": "output.json", "monitor": monitors, "scoreboard": "MatMulScoreboard",
        "connections": [f"{name} -> MatMulScoreboard" for name in monitors
                        if monitors == ["MatMulInputMonitor", "MatMulOutputMonitor"]]}}))
    return directory


@cocotb.test()
async def listed_monitors_each_watch_their_own_interface(dut):
    import importlib
    import sys

    directory = monitor_list_project(["MatMulInputMonitor", "MatMulOutputMonitor"])
    assert generate_main([str(directory / "tb.json")]) == 0
    sys.path.insert(0, str(directory))
    try:
        sys.modules.pop("mat_mul.agent.mat_mul_scoreboard", None)
        module = importlib.import_module("mat_mul.agent.mat_mul_scoreboard")
        seen = []
        module.MatMulScoreboard.on_input_monitor_callback = lambda self, item: seen.append(("input", item.data))
        module.MatMulScoreboard.on_output_monitor_callback = lambda self, item: seen.append(("output", item.data))
        env = TbEnv("env", dut, tb_config=directory / "tb.json")
    finally:
        sys.path.remove(str(directory))

    agent = env.agents["mat_mul"]
    assert sorted(agent.monitors) == ["input_monitor", "output_monitor"]
    assert list(agent.monitors["input_monitor"].interfaces) == ["input"]
    assert list(agent.monitors["output_monitor"].interfaces) == ["output"]
    env._phase("connect")
    agent.monitors["output_monitor"].publish_output(Transaction(2))
    agent.monitors["input_monitor"].publish_input(Transaction(1))
    assert seen == [("output", 2), ("input", 1)]

    source = (directory / "mat_mul" / "agent" / "mat_mul_input_monitor.py").read_text()
    assert "self.interfaces['input']" in source and "'output'" not in source
    assert not (directory / "tb_connections.md").exists()
    _, rects, edges = svg_layout((directory / "tb_diagram.svg").read_text())
    assert rects["monitor:mat_mul:output_monitor"][4] == "monitor"
    for monitor in ("input_monitor", "output_monitor"):
        assert f"monitor:mat_mul:{monitor} -> scoreboard:mat_mul:scoreboard" in edges, edges


@cocotb.test()
async def a_monitor_list_must_name_distinct_interfaces(dut):
    for monitors, expected in ((["MatMulInputMonitor", "MatMulPortMonitor"], "MatMulPortMonitor must name its interface"),
                               (["MatMulInputMonitor", "MatMulInputMonitor"], "more than one monitor is named 'input'"),
                               (["MatMulMonitor"], "MatMulMonitor must name its interface"),
                               ([], "an empty list")):
        directory = monitor_list_project(monitors)
        try:
            load_plan(directory / "tb.json")
        except ValueError as error:
            assert expected in str(error), error
        else:
            raise AssertionError(f"{monitors} was accepted")


@cocotb.test()
async def scoreboards_publish_to_scoreboards_and_stimulus(dut):
    import importlib
    import sys

    directory = Path(tempfile.mkdtemp())
    (directory / "p.json").write_text(json.dumps({"signals": [".clk"]}))
    (directory / "tb.json").write_text(json.dumps({"chain": {
        "p": "p.json", "driver": ["ChainPDriver"], "monitor": "ChainMonitor",
        "scoreboard": ["ChainCheckScoreboard", "ChainSummaryScoreboard"], "stimulus": "ChainTraffic",
        "connections": ["ChainMonitor -> ChainCheckScoreboard", "ChainCheckScoreboard -> ChainSummaryScoreboard",
                        "ChainCheckScoreboard -> ChainTraffic"]}}))
    assert generate_main([str(directory / "tb.json")]) == 0
    agent_source = directory / "chain" / "agent"
    check = (agent_source / "chain_check_scoreboard.py").read_text()
    assert "def on_monitor_callback(self, txn: ChainPTxn):" in check
    assert "self.publish(txn) delivers to: ChainSummaryScoreboard, ChainTraffic" in check
    assert "def on_check_scoreboard_callback(self, txn):" in (agent_source / "chain_summary_scoreboard.py").read_text()
    assert "def on_check_scoreboard_callback(self, txn):" in (directory / "chain/seqs/chain_traffic.py").read_text()

    sys.path.insert(0, str(directory))
    try:
        for name in ("chain_check_scoreboard", "chain_summary_scoreboard"):
            sys.modules.pop(f"chain.agent.{name}", None)
        sys.modules.pop("chain.seqs.chain_traffic", None)
        check_module = importlib.import_module("chain.agent.chain_check_scoreboard")
        summary_module = importlib.import_module("chain.agent.chain_summary_scoreboard")
        traffic_module = importlib.import_module("chain.seqs.chain_traffic")
        seen = []
        check_module.ChainCheckScoreboard.on_monitor_callback = lambda self, item: self.publish(Transaction(item.data * 10))
        summary_module.ChainSummaryScoreboard.on_check_scoreboard_callback = \
            lambda self, item: seen.append(("summary", item.data))
        traffic_module.ChainTraffic.on_check_scoreboard_callback = lambda self, item: seen.append(("stimulus", item.data))
        env = TbEnv("env", dut, tb_config=directory / "tb.json")
    finally:
        sys.path.remove(str(directory))

    agent = env.agents["chain"]
    assert list(agent.drivers) == ["p_driver"] and list(agent.drivers["p_driver"].interfaces) == ["p"]
    assert sorted(agent.scoreboards) == ["check_scoreboard", "summary_scoreboard"]
    env._phase("connect")
    agent.monitors["monitor"].publish(Transaction(4))
    assert seen == [("summary", 40), ("stimulus", 40)]


@cocotb.test()
async def generator_writes_a_makefile_that_sets_dut_parameters(dut):
    directory = Path(tempfile.mkdtemp())
    (directory / "rtl.sv").write_text("module dut_top; endmodule\n")
    (directory / "p.json").write_text(json.dumps({"signals": [".clk"], "parameters": [".WIDTH -> width"]}))
    (directory / "tb.json").write_text(json.dumps({
        "simulation": {"toplevel": "dut_top", "sources": ["rtl.sv"], "simulator": "icarus",
                       "parameters": {"WIDTH": 16}, "tests": {"smoke": "DevTraffic"}},
        "dev": {"p": "p.json", "driver": "DevDriver", "stimulus": "DevTraffic"}}))
    assert generate_main([str(directory / "tb.json")]) == 0
    makefile = (directory / "Makefile").read_text()
    for line in ("SIM ?= icarus", "COCOTB_TOPLEVEL ?= dut_top", "VERILOG_SOURCES ?= $(CURDIR)/rtl.sv",
                 "TB_CONFIG ?= $(CURDIR)/tb.json", "run the first test in simulation.tests",
                 "\t$(MAKE) sim TB_TEST=$@ COCOTB_RESULTS_FILE=results_$@.xml",
                 "COMPILE_ARGS += -P$(COCOTB_TOPLEVEL).WIDTH=16", "COMPILE_ARGS += -GWIDTH=16",
                 "include $(UVM_ZERO_ROOT)/makefiles/sim.mk"):
        assert line in makefile, line
    # No test name is copied into the Makefile: it reads them from the config.
    assert "smoke" not in makefile and "TB_TEST ?=" not in makefile
    assert "clean::\n\t@rm -f results_*.xml" in makefile

    def make_tests():
        """The TESTS make computes, evaluated without running a simulation."""
        import subprocess
        result = subprocess.run(["make", "-s", "-f", "Makefile", "-f", "-", "show-tests", f"PYTHON={sys.executable}"],
                                input="show-tests:\n\t@echo $(TESTS)\n", cwd=directory,
                                capture_output=True, text=True, check=True)
        return result.stdout.split()

    assert make_tests() == ["smoke"]
    config = json.loads((directory / "tb.json").read_text())
    config["simulation"]["tests"] = {"quick": "DevTraffic", "long_run": "DevTraffic"}
    (directory / "tb.json").write_text(json.dumps(config))
    assert make_tests() == ["quick", "long_run"]  # renamed in the JSON; the Makefile is unchanged
    driver = (directory / "dev/agent/dev_driver.py").read_text()
    assert "#     parameters (constants from the DUT): width" in driver
    assert "Driver.run() takes each item from this driver's queue" in driver

    # The Makefile is infrastructure: kept on a normal run, replaced by --refresh-infra.
    (directory / "Makefile").write_text("# mine\n")
    assert generate_main([str(directory / "tb.json")]) == 0
    assert (directory / "Makefile").read_text() == "# mine\n"
    assert generate_main([str(directory / "tb.json"), "--refresh-infra"]) == 0
    assert "COCOTB_TOPLEVEL ?= dut_top" in (directory / "Makefile").read_text()


@cocotb.test()
async def simulation_settings_are_checked(dut):
    for body, expected in (({"simulation": {"sources": ["missing.sv"]}}, "missing.sv not found"),
                           ({"simulation": {"toplevel": 3}}, "simulation.toplevel must be a name"),
                           ({"simulation": {"parameters": {"A_ROWS": 1.5}}}, "simulation.parameters must map"),
                           ({"simulation": {"seed": 1}}, "simulation: unknown settings ['seed']")):
        problems = config_problems(body)
        assert any(expected in line for line in problems), (body, problems)


def svg_layout(text):
    """The rectangles and wires of a generated diagram, after checking it is well-formed SVG."""
    from xml.etree import ElementTree
    root = ElementTree.fromstring(text)
    namespace = "{http://www.w3.org/2000/svg}"
    rects = {}
    for rect in root.iter(namespace + "rect"):
        if "data-id" in rect.attrib:
            x, y, w, h = (float(rect.get(key)) for key in ("x", "y", "width", "height"))
            rects[rect.get("data-id")] = (x, y, x + w, y + h, rect.get("data-kind"))
    edges = {edge for group in root.iter(namespace + "g") for edge in group.get("data-edges", "").split("|") if edge}
    return float(root.get("width")), rects, edges


@cocotb.test()
async def the_generator_draws_the_testbench(dut):
    directory = generator_project()
    assert generate_main([str(directory / "tb.json")]) == 0
    width, rects, edges = svg_layout((directory / "tb_diagram.svg").read_text())
    for edge in ("stimulus:gen:traffic -> handler:gen", "stimulus:gen:traffic -> handler:gen.left",
                 "handler:gen -> driver:gen:driver",
                 "driver:gen:driver -> if:gen.left.port",       # spans its child agents
                 "driver:gen:driver -> if:gen.slave_1.port",
                 "if:gen.left.port -> dut",
                 "if:gen.left.port -> monitor:gen.left:monitor",
                 "monitor:gen.slave_0:monitor -> scoreboard:gen:scoreboard",
                 # A stimulus reads interface values, which the monitors keep current.
                 "monitor:gen.left:monitor -> stimulus:gen:traffic",
                 "monitor:gen.named:monitor -> stimulus:gen:traffic"):
        assert edge in edges, edge
    for edge in edges:
        assert all(end in rects or end in ("clock", "reset") for end in edge.split(" -> ")), edge

    # The DUT in the centre, inputs on its left, active agents above, passive agents below.
    dut_left, dut_top, dut_right, dut_bottom, _ = rects["dut"]
    assert abs((dut_left + dut_right) / 2 - width / 2) < 1
    for name, (left, top, right, bottom, kind) in rects.items():
        if kind == "input":
            assert right < dut_left and top >= dut_top and bottom <= dut_bottom, name
        elif kind == "output":
            assert left > dut_right, name
    for active in ("driver:gen:driver", "handler:gen.left", "monitor:gen.left:monitor", "agent:gen"):
        assert rects[active][3] < dut_top, active
    for passive in ("monitor:gen.named:monitor", "monitor:gen.slave_1:monitor", "agent:gen.slave_0"):
        assert rects[passive][1] > dut_bottom, passive

    # No component box overlaps another.
    parts = [(name, r) for name, r in rects.items() if not name.startswith("agent:")]
    for index, (name, a) in enumerate(parts):
        for other, b in parts[index + 1:]:
            assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1], (name, other)
    assert not (directory / "tb_connections.md").exists()



@cocotb.test()
async def the_readme_architecture_diagram_is_current(dut):
    from uvm_zero_builder.diagram import architecture, render
    path = Path(__file__).resolve().parents[1] / "docs" / "architecture.svg"
    assert path.read_text() == render(architecture()), "run: python -m uvm_zero_builder.diagram docs/architecture.svg"
    _, rects, edges = svg_layout(path.read_text())
    assert {"imon -> sb", "omon -> sb", "imon -> st", "drv -> if_in", "if_out -> omon"} <= edges
    assert rects["agent"][3] < rects["dut"][1]


@cocotb.test()
async def the_readme_diagram_is_the_matrix_testbench_renamed(dut):
    from uvm_zero_builder.diagram import ARCHITECTURE_FROM_MATRIX, architecture, from_plan
    root = Path(__file__).resolve().parents[1]
    matrix = from_plan(load_plan(root / "src/examples/matrix_multiplier/tb_impl/tb.json"))
    generic = architecture()
    rename = ARCHITECTURE_FROM_MATRIX
    assert {(rename[a], rename[b]) for a, b in matrix.edges} == set(generic.edges)
    assert {rename[name]: flag for name, _, flag in matrix.interfaces} == {name: flag for name, _, flag in generic.interfaces}
    shape = {rename[box.id]: (box.active, box.simple, [[[rename[p.id] for p in row] for row in section]
                                                        for section in box.sections()])
             for box in matrix.boxes}
    assert shape == {box.id: (box.active, box.simple, [[[p.id for p in row] for row in section]
                                                        for section in box.sections()]) for box in generic.boxes}


def diagram_cases():
    """The README diagram, every example testbench, and the generator fixture."""
    from uvm_zero_builder.diagram import architecture, from_plan
    root = Path(__file__).resolve().parents[1] / "src" / "examples"
    yield "architecture", architecture()
    for config in ("matrix_multiplier/tb_impl/tb.json", "matrix_multiplier/tb_generated/tb.json",
                   "axi/tb_impl/tb.json", "axi/tb_generated/tb.json"):
        yield config, from_plan(load_plan(root / config))
    yield "generator fixture", from_plan(load_plan(generator_project() / "tb.json"))


@cocotb.test()
async def every_diagram_passes_its_audit(dut):
    # Crossings each diagram may have at most; a change that adds any fails here.
    budget = {"architecture": 1, "matrix_multiplier/tb_impl/tb.json": 1, "matrix_multiplier/tb_generated/tb.json": 1,
              "axi/tb_impl/tb.json": 0, "axi/tb_generated/tb.json": 0, "generator fixture": 12}
    from uvm_zero_builder.diagram import check
    for name, diagram in diagram_cases():
        report = check(diagram)
        assert report.problems == [], (name, report.problems)
        assert report.crossings <= budget[name], (name, report.crossings)


@cocotb.test()
async def the_diagram_audit_catches_broken_drawings(dut):
    from uvm_zero_builder.diagram import Rect, audit, best_layout
    from uvm_zero_builder.diagram import architecture
    layout, report = best_layout(architecture())
    assert report.problems == []

    # A component moved on top of another.
    saved = layout.rect["drv"]
    layout.rect["drv"] = layout.rect["hd"]
    assert any("overlaps" in problem for problem in audit(layout).problems)
    layout.rect["drv"] = saved

    # The DUT stretched across the wires around it.
    saved = layout.dut
    layout.dut = Rect(saved.x - 400, saved.y, saved.w + 800, saved.h)
    assert any("runs through dut" in problem for problem in audit(layout).problems)
    layout.dut = saved

    # A net that lost the stem to its target: it no longer reaches it, and has no arrow there.
    net = next(item for item in layout.nets if ("hd", "drv") in item.edges)
    lines = net.lines
    net.lines = [line for line in lines if not line[1]]
    problems = audit(layout).problems
    assert any("does not reach drv" in problem for problem in problems), problems
    assert any("no arrow into drv" in problem for problem in problems), problems
    net.lines = lines

    # Two different nets laid on top of each other.
    a, b = [item for item in layout.nets if item.tracks][:2]
    saved = b.tracks[0].y, b.tracks[0].stems
    b.tracks[0].y, b.tracks[0].stems = a.tracks[0].y, a.tracks[0].stems
    assert any("run together" in problem for problem in audit(layout).problems)
    b.tracks[0].y, b.tracks[0].stems = saved
    assert audit(layout).problems == []


@cocotb.test()
async def clock_and_reset_go_where_the_wiring_is_cleanest(dut):
    from uvm_zero_builder.diagram import _Layout, _default_rows, audit, best_layout
    for name, diagram in diagram_cases():
        default = audit(_Layout(diagram, _default_rows(diagram)))
        layout, best = best_layout(diagram)
        assert best.score <= default.score, name
        # Agents keep their own rows: active above the DUT, passive below.
        for box in diagram.boxes:
            if not box.simple:
                assert layout.row_of[box.id] == ("top" if box.active else "bottom"), (name, box.id)


def example_tree(directory):
    """{relative path: bytes} for every source file of an example testbench folder."""
    skip = {"__pycache__", "sim_build"}
    return {path.relative_to(directory): path.read_bytes() for path in directory.rglob("*")
            if path.is_file() and not skip & set(path.parts) and not path.name.startswith("results")}


@cocotb.test()
async def each_example_keeps_tb_generated_and_impl_in_step(dut):
    """tb/ holds only the user's JSON, tb_generated/ is tb/ plus a fresh generation,
    and tb_impl/ differs from tb_generated/ only in the protocol classes and stimuli."""
    import shutil
    import tempfile
    examples = Path(__file__).resolve().parents[1] / "src" / "examples"
    for example in ("matrix_multiplier", "axi"):
        root = examples / example
        inputs = example_tree(root / "tb")
        assert inputs and all(path.suffix == ".json" for path in inputs), (example, sorted(map(str, inputs)))

        generated = example_tree(root / "tb_generated")
        scratch = Path(tempfile.mkdtemp()) / "tb"
        shutil.copytree(root / "tb", scratch)
        (scratch.parent / "rtl").symlink_to(root / "rtl")    # tb.json names its sources as ../rtl/...
        with redirect_stdout(io.StringIO()):
            assert generate_main([str(scratch / "tb.json")]) == 0
        fresh = example_tree(scratch)
        stale = sorted(str(path) for path in set(fresh) | set(generated) if fresh.get(path) != generated.get(path))
        assert not stale, f"{example}/tb_generated is out of date ({stale}); run: make generated"

        implemented = example_tree(root / "tb_impl")
        assert set(implemented) == set(generated), (example, set(implemented) ^ set(generated))
        for path, content in generated.items():
            protocol = path.parent.name in ("agent", "seqs") and not path.name.endswith("_txn.py")
            if not protocol:
                assert implemented[path] == content, f"{example}/tb_impl/{path} differs from tb_generated"
        assert any(implemented[path] != content for path, content in generated.items()), example
