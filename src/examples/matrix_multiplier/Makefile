# Matrix multiplier example.
#   tb/            what a user writes: tb.json and the interface files
#   tb_generated/  tb/ plus everything the generator writes (rebuilt by make generated)
#   tb_impl/       tb_generated/ with the protocol filled in; what make sim runs
PYTHON ?= python
# The framework source, for source-only use; each testbench adds its own classes.
export PYTHONPATH := $(abspath ../..):$(PYTHONPATH)
.PHONY: all sim generated clean
all: sim
# Every test in tb_impl/tb.json's simulation.tests, through its generated Makefile.
sim:
	$(MAKE) -C tb_impl tests PYTHON="$(PYTHON)"
# Rebuild tb_generated/ from tb/: a copy of the inputs, then the generator's output.
generated:
	rm -rf tb_generated
	cp -r tb tb_generated
	$(PYTHON) -m uvm_zero_builder.generate tb_generated/tb.json
clean:
	$(MAKE) -C tb_impl clean PYTHON="$(PYTHON)"
