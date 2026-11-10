"""Reset UVC handler: queues pulses and holds the reset state for sequences."""
from enum import Enum, auto

from cocotb.triggers import Event

from uvm_zero_base import Handler


class ResetState(Enum):
    ResetActive = auto()
    ResetInactive = auto()


class ResetHandler(Handler):
    """Holds the system's reset state, which starts active until first released."""

    def __init__(self, name, parent=None):
        super().__init__(name, parent)
        self.reset_state = ResetState.ResetActive
        self._state_changed = Event()
        # Opt-in: restart TbEnv's top-level sequence after each reset. A sequence that
        # applies a reset itself must leave this off, or it would restart itself.
        self.restart_sequence = False

    async def wait_asserted(self):
        await self.wait_state(ResetState.ResetActive)

    async def wait_released(self):
        await self.wait_idle()
        await self.wait_state(ResetState.ResetInactive)

    async def wait_state(self, state):
        """Wait for the monitor to observe the requested state."""
        while self.reset_state is not state:
            self._state_changed.clear()
            await self._state_changed.wait()

    def observe_reset(self, transaction):
        """Monitor callback: drivers never assign observed reset state."""
        self.reset_state = ResetState.ResetActive if transaction.data["asserted"] else ResetState.ResetInactive
        self._state_changed.set()
