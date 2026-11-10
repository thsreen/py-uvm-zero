# AXI example: verify vendored RTL, lint the harnesses, and run the JSON-generated testbench in tb/.
PYTHON ?= python
VERILATOR ?= verilator
# The framework source, for source-only use; tb/ adds its own generated classes.
export PYTHONPATH := $(abspath ../..):$(PYTHONPATH)
.PHONY: all verify lint sim clean
all: lint
verify:
	$(PYTHON) verify_vendor.py
lint: verify
	@for top in axi_mux_lint axi_demux_lint axi_xbar_lint; do \
		$(VERILATOR) --lint-only --assert -Wno-fatal --top-module $$top \
			-F rtl/files.f rtl/axi_demo_cfg_pkg.sv rtl/$$top.sv || exit $$?; \
	done
# Every test in tb/tb.json's simulation.tests, through the generated tb/Makefile.
sim: verify
	$(MAKE) -C tb tests PYTHON="$(PYTHON)"
clean:
	rm -rf obj_dir
	$(MAKE) -C tb clean PYTHON="$(PYTHON)"
