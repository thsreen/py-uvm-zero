"""Read and check a TB_CONFIG description, without a DUT.

Generation and simulation validate the same description. Simulation imports the
editable agent classes previously written under agent/infra.

{"clock": {"signal": "dut.clk_i", "period_ns": 10},
 "reset": {"signal": "dut.rst_ni", "active_high": false, "duration_factor": 5},
 "axi": {"connected_module": "dut.u_axi",
         "scoreboard": "AxiScoreboard",
         "stimulus": "AxiTraffic",
         "aw": {"connected_module": ".u_aw", "port": "aw.json",
                "monitor": "AxiAwMonitor", "driver": "AxiAwDriver"},
         "slave[4]": {"connected_module": ".u_slave[{i}]", "port": "slave.json",
                      "monitor": "AxiSlaveMonitor"}}}

Top-level "clock" and "reset" create the testbench's clock and active reset; every
top-level agent then gets a passive reset UVC on the same signal. Other keys are agents:

    monitor, driver, scoreboard
        true for the base class, false or absent for none, or a class named
        <features><hints><Component>: features is the agent path in PascalCase.
        One driver or monitor uses every interface here and below. Each may also
        be a list, one per interface, whose hint names the interface:
        MatMulInputMonitor watches "input" and is the agent's "input_monitor".
        A listed scoreboard's hint is its name: MatMulDataScoreboard is "data_scoreboard".
    connections
        ["<SourceClass> -> <TargetClass>", ...]: the only routes between components,
        by class name, among the classes of this agent and below. A source class
        used by array instances connects them all. The target receives each item
        at on_<source>_callback, named from where the source sits: input_monitor
        gives on_input_monitor_callback, aw's monitor gives on_aw_monitor_callback.
    stimulus
        Stimuli registered with the agent: one class name, true, or a list. Each is
        keyed by its hint: MatMulTraffic is the agent's stimuli["traffic"]. A
        stimulus runs only when a test names it (simulation.tests) or another
        stimulus executes it.
    connected_module
        ".child" extends the parent's DUT module and "dut.path" replaces it.
    any key holding a string
        An interface name and its JSON file, relative to this file. Each interface
        gets a Transaction subclass, <features><Interface>Txn, with a field for
        every signal not tagged [Clock] or [Reset].
    any key holding an object
        A child agent; "name[N]" creates name_0 to name_N-1, replacing {i}.

Classes live next to this file: drivers, monitors, and scoreboards in <top>/agent/,
stimulus in <top>/seqs/, each in a file named after its class in snake_case.
Agent construction and connection code lives in <top>/agent/infra/.
"""
from dataclasses import dataclass, field
import importlib.util
import json
from numbers import Real
from pathlib import Path
import re
import sys

from uvm_zero_base.interface import Interface
from uvm_zero_base.settings import ENV_DEFAULTS, SCOREBOARD_DEFAULTS, check

COMPONENTS = ("monitor", "driver", "scoreboard", "stimulus")
SUFFIXES = {"monitor": "Monitor", "driver": "Driver", "scoreboard": "Scoreboard"}
PACKAGES = {"monitor": "agent", "driver": "agent", "scoreboard": "agent", "stimulus": "seqs",
            "transaction": "agent"}
# Transaction attributes a signal field must not replace.
_TRANSACTION_ATTRIBUTES = {"source", "sequence", "driver", "instance_id"}
SETTINGS = {"clock": {"signal": str, "period_ns": Real, "active": bool, "check_period": bool, "check_cycles": int},
            "reset": {"signal": str, "active_high": bool, "period_ns": Real, "duration_factor": Real,
                      "restart_sequence": bool}}
DEFAULTS = {"clock": {"period_ns": 10, "active": True, "check_period": False, "check_cycles": 500},
            "reset": {"active_high": True, "period_ns": 10, "duration_factor": 2, "restart_sequence": False}}
SIMULATION = {"toplevel": None, "sources": [], "simulator": "verilator", "compile_args": [], "parameters": {},
              "tests": {}}
# Generated Makefile targets a test name must not replace.
_MAKE_TARGETS = {"all", "sim", "clean", "regress", "generate", "tests", "results"}
_TOP_LEVEL = {*SETTINGS, "settings", "simulation"}
RESERVED_AGENT_NAMES = {"reset"}
# A top-level agent becomes a namespace package; it must not hide an existing module.
_TAKEN_MODULES = set(sys.stdlib_module_names) | {
    "uvm_zero_base", "uvm_zero_builder", "common_uvc", "cocotb", "cocotb_tools", "pytest"}
_MODULE = "connected_module"
_CONNECTION = re.compile(r"(\S+) -> (\S+)")
_SNAKE = re.compile(r"[a-z][a-z0-9_]*")
_ARRAY = re.compile(r"([a-z][a-z0-9_]*)\[(\d+)\]")
_PASCAL = re.compile(r"[A-Z][A-Za-z0-9]*")
_WORD_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


class ConfigError(ValueError):
    """The configuration breaks one or more rules; each is on its own line."""


def snake_case(name):
    return _WORD_BOUNDARY.sub("_", name).lower()


def pascal_case(name):
    return "".join(part.capitalize() for part in name.split("_"))


def class_prefix(plan):
    """The <features> part a class name must start with at this hierarchy."""
    return "".join(pascal_case(name) for name in plan)


def module_for(flag, plan, class_name):
    """The module the naming plan assigns to a class: <top>/agent/ or <top>/seqs/."""
    return f"{plan[0]}.{PACKAGES[flag]}.{snake_case(class_name)}"


def transaction_class(node, key):
    """The Transaction subclass for one of an agent's interfaces: MatMul + Ip + Txn."""
    return class_prefix(node.plan) + pascal_case(key) + "Txn"


def agent_class(node):
    """Each expanded instance gets editable construction code of its own."""
    return class_prefix(node.path) + "Agent"


def agent_module(node):
    return f"{node.plan[0]}.agent.infra.{snake_case(agent_class(node))}"


def member_hint(node, flag, class_name):
    """A listed class's hint: MatMulInputMonitor -> "input"."""
    return snake_case(class_name[len(class_prefix(node.plan)):len(class_name) - len(SUFFIXES.get(flag, ""))])


@dataclass
class Route:
    """One source instance of a "<SourceClass> -> <TargetClass>" connection, resolved
    within its declaring agent."""

    source: str
    target: str
    source_prefix: str
    source_node: object
    source_kind: str
    source_key: str
    target_prefix: str
    target_node: object
    target_kind: str
    target_key: str
    target_value: object
    callback: str
    indices: tuple


def interface_names(keys):
    """Use the interface name alone when unique, otherwise qualify by hierarchy."""
    keys = list(keys)
    leaves = [key.rsplit(".", 1)[-1] for key in keys]
    return {key: key.rsplit(".", 1)[-1] if leaves.count(key.rsplit(".", 1)[-1]) == 1
            else key.replace(".", "_") for key in keys}


@dataclass
class Node:
    """One agent of the description, after arrays are expanded."""

    name: str
    path: tuple
    plan: tuple
    indices: tuple
    connected_module: str
    active: bool = True
    components: dict = field(default_factory=dict)
    interfaces: dict = field(default_factory=dict)
    signals: dict = field(default_factory=dict)
    parameters: dict = field(default_factory=dict)
    tags: dict = field(default_factory=dict)
    children: list = field(default_factory=list)
    module_binding: str = None
    connections: list = field(default_factory=list)

    @property
    def where(self):
        return ".".join(self.path)

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()

    def classes(self):
        """Yield (flag, class name) for every extended class this agent names."""
        for flag, value in self.components.items():
            for item in value if isinstance(value, list) else [value]:
                if isinstance(item, str):
                    yield flag, item

    def subtree(self, prefix=""):
        """Yield (relative prefix, node) for this node and every descendant."""
        yield prefix, self
        for child in self.children:
            yield from child.subtree(f"{prefix}{child.name}.")

    def members(self, flag):
        """Yield (key, class name or True, interface keys) for each driver, monitor, scoreboard, or stimulus.

        A single driver, monitor, or scoreboard is keyed by its flag; a driver or
        monitor then uses every interface in the subtree. Listed ones are keyed
        <hint>_<flag>, and a listed driver or monitor uses the interface its hint
        names ("aw_port" names a child's "aw.port"). A stimulus is always keyed by
        its hint (MatMulTraffic is "traffic"), or "stimulus" for true.
        """
        value = self.components.get(flag)
        if value is None:
            return

        uses_interfaces = flag in ("driver", "monitor")
        if not isinstance(value, list):
            key = member_hint(self, flag, value) if flag == "stimulus" and value is not True else flag
            yield key, value, list(self.subtree_signals()) if uses_interfaces else []
            return

        keys = {key.replace(".", "_"): key for key in self.subtree_signals()}
        for class_name in value:
            hint = member_hint(self, flag, class_name)
            key = hint if flag == "stimulus" else f"{hint}_{flag}"
            yield key, class_name, [keys[hint]] if uses_interfaces else []

    def instances(self):
        """Yield (agent prefix, node, kind, key, class name) for each named class here and below."""
        for prefix, node in self.subtree():
            for flag in COMPONENTS:
                for key, value, _ in node.members(flag):
                    if isinstance(value, str):
                        yield prefix, node, flag, key, value

    def find(self, class_name):
        """Every instance of a class in this agent's subtree; arrays give several."""
        return [instance for instance in self.instances() if instance[4] == class_name]

    def routes(self):
        """Yield a Route for each source instance of this agent's connections.

        The target receives items at on_<source>_callback, named from the source's
        position; array instances use their declared name and pass their indices first.
        """
        for source, target in self.connections:
            target_prefix, target_node, target_kind, target_key, _ = self.find(target)[0]
            for source_prefix, source_node, source_kind, source_key, _ in self.find(source):
                name = "_".join((*source_node.plan[len(self.plan):], source_key))
                yield Route(source, target, source_prefix, source_node, source_kind, source_key, target_prefix,
                            target_node, target_kind, target_key, target, f"on_{name}_callback",
                            source_node.indices[len(self.indices):])

    def transactions(self):
        """Yield (interface key, class name, fields) for this agent's own interfaces.

        Fields are the interface's signals except those tagged [Clock] or [Reset].
        """
        for key, names in self.signals.items():
            tags = self.tags.get(key, {})
            yield key, transaction_class(self, key), [name for name in names if name not in tags]

    def transaction_for(self, key):
        """The transaction class of an interface here or below, by relative key ("aw.port")."""
        for prefix, node in self.subtree():
            for local, class_name, _ in node.transactions():
                if prefix + local == key:
                    return node, class_name
        return None, None

    def subtree_tags(self):
        """Every interface's {signal: tag} in this subtree, by relative key."""
        return {prefix + key: tags for prefix, node in self.subtree() for key, tags in node.tags.items()}

    def subtree_parameters(self):
        """Every interface's parameter names in this subtree, by relative key."""
        return {prefix + key: names for prefix, node in self.subtree() for key, names in node.parameters.items()}

    def subtree_signals(self):
        """Every interface in this subtree, by relative key, with its signal names."""
        return {prefix + key: names for prefix, node in self.subtree() for key, names in node.signals.items()}


@dataclass
class Plan:
    """A checked description: its directory, top-level agents, and clock and reset."""

    directory: Path
    agents: list
    clock: dict = None
    reset: dict = None
    settings: dict = field(default_factory=dict)
    simulation: dict = field(default_factory=lambda: dict(SIMULATION))


class _Reader:
    def __init__(self, directory):
        self.directory = directory
        self.problems = []

    def setting(self, key, value):
        rules = SETTINGS[key]
        if not isinstance(value, dict):
            self.problems.append(f"{key}: expected a JSON object")
            return None

        unknown = sorted(set(value) - set(rules))
        if unknown:
            self.problems.append(f"{key}: unknown settings {unknown}")

        if "signal" not in value:
            self.problems.append(f"{key}: a signal such as dut.{key}_i is required")

        for name, kind in rules.items():
            item = value.get(name)
            if name not in value:
                continue

            if kind is bool and type(item) is not bool:
                self.problems.append(f"{key}.{name} must be true or false")
            elif kind is Real and (type(item) is bool or not isinstance(item, Real) or item <= 0):
                self.problems.append(f"{key}.{name} must be a positive number")
            elif kind is int and (type(item) is not int or item <= 0):
                self.problems.append(f"{key}.{name} must be a positive integer")
            elif kind is str and (not isinstance(item, str) or not item):
                self.problems.append(f"{key}.{name} must be a DUT signal path")

        merged = {**DEFAULTS[key], **value}
        if key == "clock" and merged["active"] and merged["check_period"]:
            self.problems.append("clock: check_period applies only to a passive clock (active: false)")
        if key == "clock" and "check_cycles" in value and not merged["check_period"]:
            self.problems.append("clock: check_cycles requires check_period: true")

        return merged

    def simulation(self, value):
        """The "simulation" section: what the generated Makefile builds and runs."""
        if not isinstance(value, dict):
            self.problems.append("simulation must be a JSON object")
            return dict(SIMULATION)

        unknown = sorted(set(value) - set(SIMULATION))
        if unknown:
            self.problems.append(f"simulation: unknown settings {unknown}")

        merged = {**SIMULATION, **value}
        for key in ("toplevel", "simulator"):
            if merged[key] is not None and (not isinstance(merged[key], str) or not merged[key]):
                self.problems.append(f"simulation.{key} must be a name such as "
                                     + ("matrix_multiplier" if key == "toplevel" else "verilator or icarus"))
        for key in ("sources", "compile_args"):
            if not isinstance(merged[key], list) or not all(isinstance(item, str) for item in merged[key]):
                self.problems.append(f"simulation.{key} must be a list of strings")
                merged[key] = []
        for source in merged["sources"]:
            if not (self.directory / source).is_file():
                self.problems.append(f"simulation.sources: {source} not found next to the config")
        parameters = merged["parameters"]
        if not isinstance(parameters, dict) or not all(
                name.isidentifier() and (type(value) is int or isinstance(value, str))
                for name, value in parameters.items()):
            self.problems.append('simulation.parameters must map DUT parameter names to integers or '
                                 'literal strings, such as {"A_ROWS": 4}')
            merged["parameters"] = {}
        return merged

    def env_settings(self, value):
        """The "settings" section: env settings plus a "scoreboard" group."""
        if not isinstance(value, dict):
            self.problems.append("settings must be a JSON object")
            return {}

        env = {key: item for key, item in value.items() if key != "scoreboard"}
        self.problems += check(env, ENV_DEFAULTS, "settings")
        if "scoreboard" in value:
            self.problems += check(value["scoreboard"], SCOREBOARD_DEFAULTS, "settings.scoreboard")

        return value

    def agents(self, items, path, plan, indices, module):
        nodes, seen = [], set()
        for key, spec in items:
            array = _ARRAY.fullmatch(key)
            base = array[1] if array else key
            where = ".".join((*path, key))
            if array is None and not _SNAKE.fullmatch(key):
                # Report the name, but keep checking inside so every problem shows at once.
                self.problems.append(f"{where}: agent names are lower_snake_case, optionally name[N]")

            if not path and _hides_module(base, self.directory):
                self.problems.append(f"{where}: a top-level agent named {base!r} would hide the "
                                     f"existing Python module {base}")
                continue

            if base in RESERVED_AGENT_NAMES:
                self.problems.append(f"{where}: {base!r} is reserved for the agent's reset UVC")
                continue

            if array:
                instances = [(f"{base}_{index}", (*indices, index), _substitute(spec, str(index)))
                             for index in range(int(array[2]))]
            else:
                instances = [(key, indices, spec)]

            for name, child_indices, child_spec in instances:
                if name in seen:
                    self.problems.append(f"{'.'.join((*path, name))}: defined twice")
                    continue

                seen.add(name)
                node = self.agent(name, (*path, name), (*plan, base), child_indices, child_spec, module)
                if node is not None:
                    nodes.append(node)

        return nodes

    def agent(self, name, path, plan, indices, spec, module):
        where = ".".join(path)
        if not isinstance(spec, dict):
            self.problems.append(f"{where}: expected a JSON object")
            return None

        local = spec.get(_MODULE)
        if local is not None:
            if not isinstance(local, str) or not local or "{i}" in local:
                self.problems.append(f"{where}.connected_module must be a path such as dut.u_core or .child"
                                     " ({i} only inside an array)")
            else:
                module = (module or "dut") + local if local.startswith(".") else local

        active = spec.get("active", True)
        if type(active) is not bool:
            self.problems.append(f"{where}.active must be true or false")
            active = True

        node = Node(name, path, plan, indices, module, active)
        node.module_binding = local
        for flag in COMPONENTS:
            self.component(node, flag, spec.get(flag, False))

        children, unknown = [], []
        for key, value in spec.items():
            if key in COMPONENTS or key in ("active", "connections", _MODULE):
                continue

            if isinstance(value, dict):
                children.append((key, value))
            elif isinstance(value, str):
                self.interface(node, key, value)
            else:
                unknown.append(key)

        if unknown:
            self.problems.append(f"{where}: unknown settings {sorted(unknown)}")

        node.children = self.agents(children, path, plan, indices, module)
        self.member_lists(node)
        self.connections(node, spec.get("connections", []))
        if not active and ("driver" in node.components or "stimulus" in node.components):
            self.problems.append(f"{where}: a passive agent (active: false) has no driver or stimulus")

        needs_interface = "monitor" in node.components or "driver" in node.components
        if needs_interface and not any(child.interfaces for _, child in node.subtree()):
            self.problems.append(f"{where}: a monitor or driver needs an interface file here or below")

        return node

    def class_name(self, node, flag, value, where):
        """Check one class name against the naming pattern; True when it passes."""
        if not isinstance(value, str) or not _PASCAL.fullmatch(value):
            self.problems.append(f"{where} must be true, false, or a class name in PascalCase, got {value!r}")
            return False

        suffix = SUFFIXES.get(flag)
        if suffix and not value.endswith(suffix):
            self.problems.append(f"{where}: {value} should end with {suffix}")
            return False

        prefix = class_prefix(node.plan)
        if not value.startswith(prefix) or len(value) == len(prefix):
            self.problems.append(f"{where}: {value} should be named {prefix}<hints>"
                                 f"{suffix or '<Name>'}, starting with its agent path")
            return False

        return True

    def component(self, node, flag, value):
        if value is False:
            return

        if isinstance(value, list):
            where = f"{node.where}.{flag}"
            checked = [self.class_name(node, flag, item, f"{where}[{index}]") for index, item in enumerate(value)]
            if not value:
                self.problems.append(f"{where}: an empty list; use false for no monitor")
            elif all(checked):
                node.components[flag] = list(value)
            return

        if value is True or self.class_name(node, flag, value, f"{node.where}.{flag}"):
            node.components[flag] = value

    def member_lists(self, node):
        """A listed driver or monitor names one interface in its hint; a scoreboard names itself."""
        for flag in COMPONENTS:
            value = node.components.get(flag)
            if not isinstance(value, list):
                continue

            where, suffix = f"{node.where}.{flag}", SUFFIXES.get(flag, "")
            hints = [member_hint(node, flag, name) for name in value]
            if flag in ("scoreboard", "stimulus"):
                problems = [f"{where}: {name} needs a hint naming it in a list, such as "
                            f"{class_prefix(node.plan)}Data{suffix}" for name, hint in zip(value, hints) if not hint]
            else:
                keys = sorted(key.replace(".", "_") for key in node.subtree_signals())
                problems = [f"{where}: {name} must name its interface, such as "
                            f"{class_prefix(node.plan)}<Interface>{suffix} for one of {keys}"
                            for name, hint in zip(value, hints) if hint not in keys]
            problems += [f"{where}: more than one {flag} is named {hint!r}"
                         for hint in sorted(set(hints)) if hint and hints.count(hint) > 1]
            if problems:
                self.problems += problems
                del node.components[flag]

    def connections(self, node, value):
        """Check each "<SourceClass> -> <TargetClass>" entry and record it on the agent."""
        where = f"{node.where}.connections"
        if not isinstance(value, list) or not all(isinstance(entry, str) for entry in value):
            self.problems.append(f'{where} must be a list of "<SourceClass> -> <TargetClass>" strings')
            return

        known = sorted({instance[4] for instance in node.instances()})
        for entry in value:
            match = _CONNECTION.fullmatch(entry)
            if match is None:
                self.problems.append(f"{where}: {entry!r} should be '<SourceClass> -> <TargetClass>', "
                                     "one space each side")
                continue

            source, target = match.groups()
            missing = [name for name in (source, target) if not node.find(name)]
            targets = node.find(target)
            if missing:
                self.problems += [f"{where}: {name!r} in {entry!r} is not a class of this agent or below; "
                                  f"expected one of {known} (a true component has no class to name)"
                                  for name in missing]
            elif source == target:
                self.problems.append(f"{where}: {entry!r} connects a class to itself")
            elif (source, target) in node.connections:
                self.problems.append(f"{where}: {entry!r} is listed twice")
            elif len(targets) > 1:
                paths = ", ".join(prefix + key for prefix, _, _, key, _ in targets)
                self.problems.append(f"{where}: {target} has {len(targets)} instances here ({paths}); "
                                     "declare the connection inside the agent that holds one")
            else:
                node.connections.append((source, target))

    def interface(self, node, key, value):
        where = f"{node.where}.{key}"
        if not _SNAKE.fullmatch(key):
            self.problems.append(f"{where}: interface names are lower_snake_case")

        path = self.directory / value
        node.interfaces[key] = path
        try:
            signals, parameters, tags, _ = Interface.maps(path)
        except (OSError, ValueError, TypeError) as error:
            self.problems.append(f"{where}: {error}")
        else:
            node.signals[key] = list(signals)
            node.parameters[key] = list(parameters)
            node.tags[key] = tags
            clashes = sorted((set(signals) - set(tags)) & _TRANSACTION_ATTRIBUTES)
            if clashes:
                self.problems.append(f"{where}: signal names {clashes} would replace Transaction attributes; "
                                     "rename them with '-> name'")


def _substitute(value, index):
    """Replace {i} with this array's index, leaving nested arrays their own {i}."""
    if isinstance(value, str):
        return value.replace("{i}", index)

    if isinstance(value, list):
        return [_substitute(item, index) for item in value]

    if isinstance(value, dict):
        return {key: item if _ARRAY.fullmatch(key) and isinstance(item, dict) else _substitute(item, index)
                for key, item in value.items()}

    return value


def _hides_module(name, directory):
    """True when name is taken by a module outside the config directory."""
    if name in _TAKEN_MODULES:
        return True

    try:
        spec = importlib.util.find_spec(name)
    except (ImportError, ValueError):
        return False

    if spec is None or spec.origin in (None, "namespace"):
        return False

    locations = [spec.origin, *(spec.submodule_search_locations or [])]
    return not any(Path(location).resolve().is_relative_to(directory.resolve()) for location in locations)


def _check_tests(nodes, simulation, problems):
    """Each test names a stimulus registered with exactly one agent instance."""
    tests = simulation["tests"]
    if not isinstance(tests, dict) or not all(isinstance(name, str) and isinstance(value, str)
                                              for name, value in tests.items()):
        problems.append('simulation.tests must map test names to stimulus classes, such as {"smoke": "MatMulTraffic"}')
        simulation["tests"] = {}
        return

    registered = [(node.where, value) for top in nodes for node in top.walk()
                  for _, value, _ in node.members("stimulus") if isinstance(value, str)]
    for name, class_name in tests.items():
        where = f"simulation.tests.{name}"
        found = [path for path, value in registered if value == class_name]
        if not _SNAKE.fullmatch(name) or name in _MAKE_TARGETS:
            problems.append(f"{where}: test names are lower_snake_case and not one of {sorted(_MAKE_TARGETS)}")
        if not found:
            problems.append(f"{where}: {class_name} is not a stimulus registered with an agent; "
                            f"registered: {sorted({value for _, value in registered})}")
        elif len(found) > 1:
            problems.append(f"{where}: {class_name} is registered by {len(found)} agents ({', '.join(found)}); "
                            "a test needs exactly one")


def callbacks(nodes, problems=None):
    """{(kind, class name): {callback: route}}: the callbacks each target class needs.

    Array instances share a class, so the same callback may come from several
    routes; two different sources must not share one, which is reported to problems.
    """
    found = {}
    for top in nodes:
        for node in top.walk():
            for route in node.routes():
                if not isinstance(route.target_value, str):
                    continue

                identity = (route.source_node.plan, route.source_key, len(route.indices))
                known = found.setdefault((route.target_kind, route.target_value), {}).setdefault(
                    route.callback, route)
                if (known.source_node.plan, known.source_key, len(known.indices)) != identity and problems is not None:
                    problems.append(f"{node.where}.connections: {route.source!r} and {known.source!r} would "
                                    f"share {route.target_value}.{route.callback}")

    return found


def _check_files(nodes, problems):
    """Every class file must be unique: one class per file, one file per class."""
    owners = {}
    for top in nodes:
        for node in top.walk():
            for flag, class_name in node.classes():
                module = module_for(flag, node.plan, class_name)
                owner = owners.setdefault(module, (node.plan, class_name, node.where))
                if owner[:2] != (node.plan, class_name):
                    problems.append(f"{node.where}: {class_name} would share the file of "
                                    f"{owner[2]}'s {owner[1]} ({module.replace('.', '/')}.py)")

            for key, class_name, _ in node.transactions():
                module = module_for("transaction", node.plan, class_name)
                owner = owners.setdefault(module, (node.plan, class_name, node.where))
                if owner[:2] != (node.plan, class_name):
                    problems.append(f"{node.where}.{key}: {class_name} would share the file of "
                                    f"{owner[2]}'s {owner[1]} ({module.replace('.', '/')}.py)")

            module = agent_module(node)
            owner = owners.setdefault(module, (node.path, agent_class(node), node.where))
            if owner[0] != node.path:
                problems.append(f"{node.where}: generated agent would share the file of {owner[2]}")


def load_plan(path, *, clock=None, reset=None):
    """Read a description and check every rule; raise ConfigError listing all problems.

    clock and reset override the file's sections key by key (from TB_ENV_CONFIG).
    """
    path = Path(path)
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ConfigError(f"{path}: {error}") from error

    if not isinstance(config, dict):
        raise ConfigError(f"{path}: expected a JSON object of agents")

    reader = _Reader(path.parent)
    for key, override in (("clock", clock), ("reset", reset)):
        if override:
            base = config.get(key, {})
            config[key] = {**base, **override} if isinstance(base, dict) and isinstance(override, dict) else override

    sections = {key: reader.setting(key, config[key]) for key in SETTINGS if key in config}
    env = reader.env_settings(config["settings"]) if "settings" in config else {}
    simulation = reader.simulation(config["simulation"]) if "simulation" in config else dict(SIMULATION)
    items = [(key, value) for key, value in config.items() if key not in _TOP_LEVEL]
    nodes = reader.agents(items, (), (), (), None)
    _check_tests(nodes, simulation, reader.problems)
    _check_files(nodes, reader.problems)
    callbacks(nodes, reader.problems)
    if reader.problems:
        raise ConfigError("\n".join(reader.problems))

    return Plan(path.parent, nodes, sections.get("clock"), sections.get("reset"), env, simulation)
