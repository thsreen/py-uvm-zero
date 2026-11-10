"""Common cocotb test selected by every simulation Makefile by default."""

import cocotb

from .test_config import TestConfig


@cocotb.test()
async def run_tb(dut):
    """Load Makefile choices, create the testbench, and run its lifecycle."""
    config = TestConfig.from_environment()
    tb_env = config.create_env(dut)
    await tb_env.run_test()
