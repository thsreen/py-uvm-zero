"""Agent: groups drivers, monitors, scoreboards, registered stimuli, and child agents."""
from .component import Component
from .driver import Driver
from .interface import Interface
from .monitor import Monitor
from .handler import Handler
from .scoreboard import Scoreboard
from .stimulus import Stimulus


_UNSET = object()


class Agent(Component):
    """A hierarchy node with declarative, named driver and monitor factories.

    Subclasses may define agent_types, driver_types, monitor_types, scoreboard_types,
    and stimulus_types, or pass them to the constructor. Factories receive (name, parent);
    functools.partial supplies protocol options. agent_options supplies
    constructor settings to named child agents. Arguments left out inherit the class
    defaults; an explicit {} or None disables them.

    Nothing is connected automatically except each driver to its queue in the
    agent's handler: connect monitors, scoreboards and other components in
    connect(), as the generated agents do from the JSON "connections".
    """

    agent_types = {}
    driver_types = {}
    monitor_types = {}
    scoreboard_types = {}
    stimulus_types = {}
    handler_type = Handler
    # Control UVCs keep their interfaces out of an ancestor handler's interface view.
    forward_monitors = True

    def __init__(self, name, parent=None, active=True, *,
                 driver_types=None, monitor_types=None, agent_types=None, scoreboard_types=None,
                 handler_type=_UNSET, stimulus_types=None, agent_options=None,
                 interface=None, interfaces=None):
        if not active and (driver_types or stimulus_types):
            raise ValueError(f"{name}: a passive agent (active=False) takes no drivers or stimuli")

        super().__init__(name, parent)
        self.active = active
        self.interfaces = Interface.collect(interface, interfaces)

        self.monitors = self._build(self.monitor_types if monitor_types is None else monitor_types, Monitor)
        self.drivers = self._build(self.driver_types if driver_types is None else driver_types, Driver) if active else {}
        # One handler for the whole agent, holding a queue per driver.
        handler_type = self.handler_type if handler_type is _UNSET else handler_type
        self.handler = handler_type("handler", self) if handler_type else None

        self.scoreboards = self._build(
            self.scoreboard_types if scoreboard_types is None else scoreboard_types, Scoreboard)
        # Registered stimuli: started only by a test (simulation.tests) or another stimulus.
        self.stimuli = self._build(
            self.stimulus_types if stimulus_types is None else stimulus_types, Stimulus) if active else {}

        agent_types = self.agent_types if agent_types is None else agent_types
        options = agent_options or {}
        if set(options) - set(agent_types):
            raise ValueError("agent_options contains an undeclared child agent")

        for key, factory in agent_types.items():
            factory(key, self, **options.get(key, {}))

    @property
    def agents(self):
        """Child agents by name, however they were created."""
        return {child.name: child for child in self.children if isinstance(child, Agent)}

    def _build(self, factories, base):
        components = {}
        for key, factory in factories.items():
            component = factory(key, self)
            if not isinstance(component, base):
                raise TypeError(f"{self.path}.{key}: factory must produce a {base.__name__}")
            components[key] = component

        return components

    def interface_map(self, prefix=""):
        """Every interface of this agent and its protocol descendants: "ip", "aw.port"."""
        found = {prefix + key: interface for key, interface in self.interfaces.items()}
        for child in self.agents.values():
            if child.forward_monitors:
                found.update(child.interface_map(f"{prefix}{child.name}."))

        return found

    def connect(self):
        """Give each driver its queue in the agent's handler.

        Override to connect components, calling super().connect() to keep the
        driver pairing, for example:
        self.scoreboards["scoreboard"].subscribe(self.monitors["monitor"], self.scoreboards["scoreboard"].on_monitor_callback)
        """
        if self.handler is not None:
            self.handler.interfaces = self.interface_map()
            for driver in self.drivers.values():
                self.handler.register_driver(driver)

        self.connect_callbacks()

    def connect_callbacks(self):
        """Connect components' callbacks: monitor -> scoreboard and so on.

        Generated agents fill this in from the JSON "connections". Nothing is
        connected by default.
        """
