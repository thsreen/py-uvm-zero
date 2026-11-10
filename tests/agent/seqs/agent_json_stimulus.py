"""Test fixture: a sequence that records where it ran."""
from uvm_zero_base import Stimulus


class AgentJsonStimulus(Stimulus):
    runs = []

    async def run(self):
        AgentJsonStimulus.runs.append(self.path)
