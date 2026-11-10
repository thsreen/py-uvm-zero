"""Interface: the DUT signals and parameters a driver or monitor uses, resolved from JSON."""
import json
import keyword
from pathlib import Path
import re

# A JSON signal entry: "<DUT path>" or "<DUT path> -> <name>", one space each side of "->",
# optionally tagged " [Clock]" or " [Reset]".
_ENTRY = re.compile(r"(\S+)(?: -> ([A-Za-z_]\w*))?(?: \[(Clock|Reset)\])?")
TAGS = ("Clock", "Reset")
_MODES = {"signals", "interface", "interfaces"}
_KEYS = _MODES | {"connected_module", "extra_signals", "parameters"}


class Values:
    """The status monitors last observed on an interface, by signal name; read only.

    Read interface.values.valid or interface.values["valid"]. Only the interface's
    monitors update it; drivers and sequences read it.
    """

    def __init__(self):
        object.__setattr__(self, "_current", {})

    def __getattr__(self, name):
        try:
            return self._current[name]
        except KeyError:
            raise AttributeError(f"no observed value for {name!r}; is a monitor bound to this interface?") from None

    def __getitem__(self, name):
        return self._current[name]

    def __contains__(self, name):
        return name in self._current

    def __iter__(self):
        return iter(self._current)

    def __len__(self):
        return len(self._current)

    def __setattr__(self, name, value):
        raise AttributeError("interface values are updated by the interface's monitors only")

    def _replace(self, current):
        object.__setattr__(self, "_current", current)


class Interface:
    """Expose only the DUT signals and parameters mapped for a driver or monitor.

    Paths may be root-relative ("start"), rooted ("dut.hier1.signal"),
    or connected-module-relative (".start"). Any part may be indexed ("gen[0].sig").
    Signals are cocotb handles. Parameters are constants, read once from the
    elaborated DUT like an RTL parameter: interface.rows is an int, never driven
    or sampled. values holds what the monitors last observed on each signal.
    """

    @staticmethod
    def collect(interface, interfaces):
        """Validate constructor arguments and return a name-to-interface dictionary."""
        if interface is not None and interfaces is not None:
            raise ValueError("Use interface or interfaces, not both")

        if interfaces is not None:
            return dict(interfaces)

        return {} if interface is None else {"default": interface}

    def __init__(self, dut, *, connected_module="dut", parameters=None, tags=None, **signals):
        """tags marks signals as clocks or resets: {"clk": "Clock", "rst_n": "Reset"}."""
        self.dut = dut
        self.connected_module = connected_module
        self.module = self._lookup(connected_module)
        self.signals = {}
        self.parameters = {}
        self.clocks = {}
        self.resets = {}
        self.values = Values()
        self._observer = None
        for alias, path in (parameters or {}).items():
            handle = self._handle(alias, path)
            if not handle.is_const:
                raise ValueError(f"DUT path {path!r} is a signal, not a parameter; list it under signals")

            self.parameters[alias] = self._constant(handle)
            setattr(self, alias, self.parameters[alias])

        for alias, path in signals.items():
            signal = self._handle(alias, path)
            if signal.is_const:
                raise ValueError(f"DUT path {path!r} is a parameter, not a signal; list it under parameters")

            self.signals[alias] = signal
            setattr(self, alias, signal)

        for alias, tag in (tags or {}).items():
            if alias not in self.signals or tag not in TAGS:
                raise ValueError(f"Tag {tag!r} on {alias!r}: tag a signal as one of {', '.join(TAGS)}")
            (self.clocks if tag == "Clock" else self.resets)[alias] = self.signals[alias]

    def _handle(self, alias, path):
        if not alias.isidentifier() or keyword.iskeyword(alias) or hasattr(self, alias):
            raise ValueError(f"Invalid or reserved name: {alias}")

        handle = self._lookup(self.connected_module + path if path.startswith(".") else path)
        if not hasattr(handle, "value"):
            raise ValueError(f"DUT path {path!r} is not a value signal or parameter")

        return handle

    def current(self, name):
        """A signal's live DUT value, read now; nothing is stored."""
        return self.signals[name].value

    def _sample(self):
        """Monitor side only: record every signal's present value in values; clocks are not tracked."""
        self.values._replace({name: signal.value for name, signal in self.signals.items()
                              if name not in self.clocks})

    @staticmethod
    def _constant(handle):
        """A parameter's elaborated value: an int where it has one, else as cocotb gives it."""
        value = handle.value
        try:
            return int(value)
        except (TypeError, ValueError):
            return value

    def _lookup(self, path):
        relative = "" if path == "dut" else path.removeprefix("dut.")
        handle = self.dut
        try:
            for part in relative.split(".") if relative else ():
                name, *indices = re.split(r"[\[\]]+", part.rstrip("]"))
                handle = getattr(handle, name)
                for index in indices:
                    handle = handle[int(index)]
        except (AttributeError, IndexError, KeyError, ValueError) as error:
            raise ValueError(f"DUT path {path!r} not found") from error

        return handle

    @classmethod
    def signal_map(cls, path, *, interface=None, connected_module=None):
        """Read a JSON file without a DUT: return ({name: DUT path}, connected module)."""
        signals, _, _, module = cls.maps(path, interface=interface, connected_module=connected_module)
        return signals, module

    @classmethod
    def maps(cls, path, *, interface=None, connected_module=None):
        """Read a JSON file without a DUT.

        Returns ({signal: DUT path}, {parameter: DUT path}, {signal: tag}, connected module).
        """
        signals, parameters, module = cls._load(Path(path), interface, connected_module, ())
        names, tags = set(), {}
        signals = cls._names(path, signals, names, tags)
        return signals, cls._names(path, parameters, names, None), tags, module or "dut"

    @staticmethod
    def _names(path, entries, taken, tags):
        """{name: DUT path} for "<DUT path>[ -> <name>][ [Tag]]" entries; names are unique.

        tags collects {name: "Clock" or "Reset"}; None means tags are not allowed here.
        """
        signals = {}
        for entry in entries:
            match = _ENTRY.fullmatch(entry)
            if match is None or "->" in match[1]:
                raise ValueError(f"{path}: Invalid signal entry {entry!r}; expected '<DUT path>' or "
                                 "'<DUT path> -> <name>', optionally followed by ' [Clock]' or ' [Reset]'")

            signal, renamed, tag = match.groups()
            if tag and tags is None:
                raise ValueError(f"{path}: {entry!r}: only signals take a [{tag}] tag, not parameters")
            alias = renamed or signal.rsplit(".", 1)[-1]
            if keyword.iskeyword(alias):
                raise ValueError(f"{path}: signal name {alias!r} is a Python keyword; rename it with '-> name'")
            if not alias.isidentifier():
                raise ValueError(f"{path}: {entry!r} gives the name {alias!r}, which is not a Python name; "
                                 "rename it with '-> name'")

            if alias in taken:
                raise ValueError(f"{path}: duplicate signal name {alias!r}")

            taken.add(alias)
            signals[alias] = signal
            if tag:
                tags[alias] = tag

        return signals

    @classmethod
    def from_json(cls, dut, path, *, interface=None, connected_module=None):
        """Build an interface from a JSON file; interface selects a bundle role.

        A file holds "signals", a reference to another file in "interface", or
        named roles in "interfaces". References are relative to their file. An
        outer "connected_module" wins over an absolute inner one, and a relative
        inner one (".child") extends it. An entry in "interfaces" may set an
        absolute module to override the bundle for that role alone. The
        connected_module argument acts as the outermost module.
        """
        signals, parameters, tags, module = cls.maps(path, interface=interface, connected_module=connected_module)
        try:
            return cls(dut, connected_module=module, parameters=parameters, tags=tags, **signals)
        except (TypeError, ValueError) as error:
            raise ValueError(f"{path}: {error}") from error

    @classmethod
    def _load(cls, path, role, module, stack):
        path = path.resolve()
        if path in stack:
            raise ValueError("Circular interface JSON reference: " +
                             " -> ".join(str(item) for item in (*stack, path)))

        try:
            definition = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(f"{path}: invalid JSON: {error.msg}") from error

        return cls._resolve(definition, path, role, module, (*stack, path))

    @classmethod
    def _resolve(cls, definition, path, role, module, stack):
        """Return (signal entries, parameter entries, connected module) for one JSON object."""
        if isinstance(definition, list):
            definition = {"signals": definition}

        if set(definition) - _KEYS or len(set(definition) & _MODES) != 1:
            raise ValueError(f"{path}: provide exactly one of signals, interface, or interfaces")

        parameters = definition.get("parameters", [])
        if not isinstance(parameters, list) or not all(isinstance(entry, str) for entry in parameters):
            raise ValueError(f'{path}: parameters must be a list such as [".WIDTH", ".A_ROWS -> rows"]')

        local = definition.get("connected_module")
        if local is not None and local.startswith("."):
            module = (module or "dut") + local
        elif module is None:
            module = local

        if "signals" in definition:
            if role is not None:
                raise ValueError(f"{path}: no named interfaces to select")

            if "extra_signals" in definition:
                raise ValueError(f"{path}: extra_signals requires an interface reference")

            return definition["signals"], parameters, module

        if "interfaces" in definition:
            if role not in definition["interfaces"]:
                raise ValueError(f"{path}: select an existing named interface, got {role!r}")

            reference, role = definition["interfaces"][role], None
        else:
            reference = definition["interface"]

        if isinstance(reference, dict):
            # An absolute module on an inline entry overrides the bundle for that role.
            if not reference.get("connected_module", ".").startswith("."):
                module = None

            # An inline definition keeps the caller's role, as a referenced file does.
            entries, inner, module = cls._resolve(reference, path, role, module, stack)
        else:
            entries, inner, module = cls._load(path.parent / reference, role, module, stack)

        return entries + definition.get("extra_signals", []), inner + parameters, module
