# AXI example: verify vendored RTL, lint the harnesses, and run the testbench.
#   tb/            what a user writes: tb.json and the interface files
#   tb_generated/  tb/ plus everything the generator writes (rebuilt by make generated)
#   tb_impl/       tb_generated/ with the protocol filled in; what make sim runs
PYTHON ?= python
VERILATOR ?= verilator
# The framework source, for source-only use; each testbench adds its own classes.
export PYTHONPATH := $(abspath ../..):$(PYTHONPATH)
.PHONY: all verify lint sim generated clean
all: lint
verify:
	$(PYTHON) verify_vendor.py
lint: verify
	@for top in axi_mux_lint axi_demux_lint axi_xbar_lint; do \
		$(VERILATOR) --lint-only --assert -Wno-fatal --top-module $$top \
			-F rtl/files.f rtl/axi_demo_cfg_pkg.sv rtl/$$top.sv || exit $$?; \
	done
# Every test in tb_impl/tb.json's simulation.tests, through its generated Makefile.
sim: verify
	$(MAKE) -C tb_impl tests PYTHON="$(PYTHON)"
# Rebuild tb_generated/ from tb/: a copy of the inputs, then the generator's output.
generated:
	rm -rf tb_generated
	cp -r tb tb_generated
	$(PYTHON) -m uvm_zero_builder.generate tb_generated/tb.json
clean:
	rm -rf obj_dir
	$(MAKE) -C tb_impl clean PYTHON="$(PYTHON)"
