"""Translate the simulation Makefile's choices into one TbEnv constructor call."""

from dataclasses import dataclass, field
from importlib import import_module
import inspect
import json
import os
from pathlib import Path

from .stimulus import Stimulus
from .tb_env import TbEnv


def load_type(selector, base_type, option):
    """Import the class named by a "module:Class" selector."""
    module, separator, name = selector.partition(":")
    if not separator or not module or not name:
        raise ValueError(f"{option} must be module:Class, got {selector!r}")

    selected = getattr(import_module(module), name)
    if not isinstance(selected, type) or not issubclass(selected, base_type):
        raise TypeError(f"{option} must select a {base_type.__name__} subclass")

    return selected


@dataclass
class TestConfig:
    """The environment class, instance name, and its constructor arguments."""

    env_type: type
    env_name: str = "tb_env"
    env_config: dict = field(default_factory=dict)

    @classmethod
    def from_environment(cls):
        """Load the selectors and JSON files exported by the simulation Makefile."""
        env_type = load_type(os.environ.get("TB_ENV", ""), TbEnv, "TB_ENV")
        env_config = cls._read_config(os.environ.get("TB_ENV_CONFIG", ""))

        interface_config = os.environ.get("TB_INTERFACE_CONFIG", "")
        if interface_config:
            if "interface_config" not in inspect.signature(env_type).parameters:
                raise ValueError(f"TB_INTERFACE_CONFIG is set, but {env_type.__name__} takes no interface_config")

            env_config["interface_config"] = interface_config

        tb_config = os.environ.get("TB_CONFIG", "")
        if tb_config:
            env_config["tb_config"] = tb_config

        sequence = os.environ.get("TB_SEQUENCE", "")
        if sequence and tb_config:
            raise ValueError("With TB_CONFIG, choose a test from simulation.tests with TB_TEST, not TB_SEQUENCE")
        if sequence:
            env_config["sequence_type"] = load_type(sequence, Stimulus, "TB_SEQUENCE")

        test = os.environ.get("TB_TEST", "")
        if test:
            env_config["test"] = test

        sequence_config = os.environ.get("TB_SEQUENCE_CONFIG", "")
        if sequence_config:
            env_config["sequence_config"] = cls._read_config(sequence_config)

        return cls(env_type, os.environ.get("TB_ENV_NAME", "tb_env"), env_config)

    def create_env(self, dut):
        """Pass the resolved configuration directly to the environment."""
        return self.env_type(self.env_name, dut, **self.env_config)

    @staticmethod
    def _read_config(filename):
        if not filename:
            return {}

        config = json.loads(Path(filename).read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            raise ValueError(f"{filename}: test configuration must be a JSON object")

        return config

