"""Scoreboard: callback delivery, shared heartbeat, and optional observation history."""
from collections import deque
from functools import partial

from .component import Component
from .settings import SCOREBOARD_DEFAULTS

_UNSET = object()


class Scoreboard(Component):
    """Base plumbing only; the user owns matching, queues, deadlines and check_phase()."""

    def __init__(self, name, parent=None, *, history=_UNSET):
        super().__init__(name, parent)
        defaults = getattr(self.root, "scoreboard_settings", SCOREBOARD_DEFAULTS)
        self.transactions = deque(maxlen=defaults["history"] if history is _UNSET else history)

    def subscribe(self, source, callback, *, interface=None, indices=()):
        """Deliver every item a component publishes to one checking callback.

        source is any component; a monitor's interface= narrows it to one interface.
        The wrapper records the item and emits heartbeat before calling callback,
        passing indices first. Routing follows the connection, never transaction.source.
        """
        deliver = partial(self.callback, callback=callback, indices=indices)
        if interface is None:
            source.add_callback(deliver)
        else:
            source.add_callback(deliver, interface=interface)

    def callback(self, transaction, *, callback=None, indices=()):
        """Record an observation and call the selected checker (or process())."""
        self.heartbeat()
        self.transactions.append(transaction)
        (callback or self.process)(*indices, transaction)

    def process(self, transaction):
        """Override for observations delivered without a named interface callback."""

    def heartbeat(self):
        """Any scoreboard callback resets the environment's shared idle window."""
        self.root.note_activity()
