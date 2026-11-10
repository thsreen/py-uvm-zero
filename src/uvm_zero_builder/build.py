"""Create a testbench from a checked TB_CONFIG plan: clock, reset, and agents."""
from importlib import import_module, invalidate_caches
from pathlib import Path
import sys

from uvm_zero_base.agent import Agent
from uvm_zero_base.interface import Interface
from .plan import agent_class, agent_module


def subtree(agent, kind, prefix=""):
    """Map one of interfaces, drivers, or monitors across an agent's subtree.

    Keys are relative to the agent: "driver" there, "aw.driver" in child agent aw.
    """
    found = {prefix + key: value for key, value in getattr(agent, kind).items()}
    for child in agent.children:
        if isinstance(child, Agent):
            found.update(subtree(child, kind, f"{prefix}{child.name}."))

    return found


def _instantiate_agent(parent, node, directory):
    """Load the agent's editable construction code; never synthesize an agent here."""
    module = agent_module(node)
    try:
        selected = getattr(import_module(module), agent_class(node))
    except ModuleNotFoundError as error:
        if error.name is None or not (module == error.name or module.startswith(error.name + ".")):
            raise
        raise ValueError(f"{node.where}: missing {module}; run uvm-zero-generate on TB_CONFIG first") from error

    if not isinstance(selected, type) or not issubclass(selected, Agent):
        raise TypeError(f"{module}.{agent_class(node)} must be an Agent subclass")

    return selected(node.name, parent, config_dir=directory, connected_module=node.connected_module)


def _build_clock_and_reset(env, plan):
    """The JSON's clock and active reset, at the top of the testbench."""
    # Imported here: common_uvc itself builds on uvm_zero_base.
    from common_uvc import ClockAgent, ResetAgent

    clock = None
    if plan.clock is not None:
        settings = plan.clock
        interface = Interface(env.dut, clk=settings["signal"], tags={"clk": "Clock"})
        checks = ({"check_period": True, "check_cycles": settings["check_cycles"]}
                  if settings["check_period"] else {})
        env.clock = ClockAgent("clock", env, active=settings["active"], clock_signal="clk",
                               period_ns=settings["period_ns"], interfaces={"clock": interface}, **checks)
        clock = interface.clk
        if env.heartbeat_clock is None:
            env.heartbeat_clock = clock

    if plan.reset is not None:
        settings = plan.reset
        env.reset = ResetAgent("reset", env, reset_signal="reset", active_high=settings["active_high"],
                               period_ns=settings["period_ns"], duration_factor=settings["duration_factor"],
                               interfaces={"reset": Interface(env.dut, reset=settings["signal"], tags={"reset": "Reset"})})
        env.reset.drivers["driver"].release_clock = clock
        env.reset.handler.restart_sequence = settings["restart_sequence"]
        if env.reset_handler is None:
            env.reset_handler = env.reset.handler


def _passive_reset(env, plan):
    """A factory for each agent's passive reset UVC, watching the JSON's reset signal."""
    if env.agent_reset_type is not None:
        return env.agent_reset_type

    if plan.reset is None:
        return None

    from common_uvc import ResetAgent

    settings = plan.reset

    def factory(name, parent):
        return ResetAgent(name, parent, active=False, reset_signal="reset",
                          active_high=settings["active_high"], period_ns=settings["period_ns"],
                          duration_factor=settings["duration_factor"],
                          interfaces={"reset": Interface(env.dut, reset=settings["signal"], tags={"reset": "Reset"})})

    return factory


def _use_config_directory(directory):
    """Load this config's modules with fresh package objects when their origin changes.

    Evict their package trees as well: namespace packages retain child-module
    attributes used by ``from package import helper``. Old environments keep their
    existing module objects; only future imports use the new package tree.
    """
    if str(directory) in sys.path:
        sys.path.remove(str(directory))
    sys.path.insert(0, str(directory))

    stale = set()
    for name, module in list(sys.modules.items()):
        loaded = getattr(module, "__file__", None)
        if loaded is None:
            continue

        base = directory / Path(*name.split("."))
        own = [path for path in (base.with_suffix(".py"), base / "__init__.py") if path.exists()]
        if own and Path(loaded).resolve() not in {path.resolve() for path in own}:
            stale.add(name)
            parts = name.split(".")
            for depth in range(1, len(parts)):
                parent = ".".join(parts[:depth])
                if (directory / Path(*parts[:depth])).is_dir() and hasattr(sys.modules.get(parent), "__path__"):
                    stale.add(parent)

    for name in list(sys.modules):
        if any(name == prefix or name.startswith(prefix + ".") for prefix in stale):
            del sys.modules[name]

    invalidate_caches()


def build_testbench(env, plan):
    """Create the clock, reset, and agents of a checked plan under env."""
    # Generated classes live next to the config, so its directory is imported first.
    directory = plan.directory.resolve()
    _use_config_directory(directory)

    _build_clock_and_reset(env, plan)
    reset_factory = _passive_reset(env, plan)
    for node in plan.agents:
        agent = _instantiate_agent(env, node, directory)
        if reset_factory is not None:
            reset_factory("reset", agent)
