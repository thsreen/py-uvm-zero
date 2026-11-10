"""Transaction: the item passed between stimulus, drivers, monitors, and scoreboards."""
import dataclasses


class Transaction:
    """Data plus where it came from, for routing and debugging.

    source is where the item originated (a sequence or monitor); sequence and
    driver are the hierarchy paths of the sequence that last sent it and the
    driver that drove it. Equality compares payload data only.
    Protocol items may instead be dataclass subclasses with their own fields.
    """

    data = None
    source = None
    instance_id = None
    sequence = None
    driver = None

    def __init__(self, data=None, *, source=None, instance_id=None):
        self.data = data
        self.source = source
        self.instance_id = instance_id

    @classmethod
    def from_values(cls, values):
        """A dataclass transaction from an interface's observed values, field by field.

        MatMulIpTransaction.from_values(self.interfaces["ip"].values) in a monitor.
        """
        return cls(**{field.name: values[field.name] for field in dataclasses.fields(cls)
                      if field.init and field.name in values})

    @classmethod
    def idle_values(cls):
        """Each signal field's value while idle, such as during reset: 0 unless overridden.

        A driver's drive_idle() writes these; drive_values() spreads a single value
        over every element of an array signal.
        """
        return {field.name: 0 for field in dataclasses.fields(cls) if field.init}

    def signal_values(self):
        """The dataclass fields that are set, by name, for driver.drive_values(interface, **...)."""
        return {field.name: getattr(self, field.name) for field in dataclasses.fields(self)
                if getattr(self, field.name) is not None}

    def __eq__(self, other):
        if not isinstance(other, Transaction):
            return NotImplemented
        return self.data == other.data

    def __hash__(self):
        return hash(self.data)

    def __repr__(self):
        trace = "".join(f", {name}={getattr(self, name)!r}" for name in ("sequence", "driver")
                        if getattr(self, name) is not None)
        return (f"Transaction({self.data!r}, source={self.source!r}, "
                f"instance_id={self.instance_id!r}{trace})")
