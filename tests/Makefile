# Framework self-tests. Icarus is enough: no AXI RTL is involved.
PYTHON ?= python
SIM ?= icarus
TOPLEVEL_LANG := verilog
COCOTB_TOPLEVEL ?= top
VERILOG_SOURCES := $(CURDIR)/top.sv
COMPILE_ARGS += -g2012
COCOTB_TEST_MODULES ?= lifecycle_tests,component_tests,reset_tests,interface_tests,builder_tests

export PYTHONPATH := $(CURDIR):$(abspath ../src):$(PYTHONPATH)

include $(shell $(PYTHON) -m cocotb_tools.config --makefiles)/Makefile.sim
