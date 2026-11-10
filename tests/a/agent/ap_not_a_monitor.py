"""Test fixture: a class named as a monitor that is not one."""
from uvm_zero_base import Driver


class APNotAMonitor(Driver):
    pass
