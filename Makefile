# Top-level entry points: compile, framework self-tests, and the AXI and matrix examples.
PYTHON ?= python
.PHONY: all test compile framework-test axi-verify axi-lint axi-sim matrix-sim clean
all: test
test: compile framework-test axi-lint axi-sim matrix-sim
compile:
	$(PYTHON) -m compileall -q src
framework-test:
	$(MAKE) -C tests PYTHON="$(PYTHON)"
axi-verify:
	$(MAKE) -C src/examples/axi verify PYTHON="$(PYTHON)"
axi-lint:
	$(MAKE) -C src/examples/axi lint PYTHON="$(PYTHON)"
axi-sim:
	$(MAKE) -C src/examples/axi sim PYTHON="$(PYTHON)"
# The matrix testbench, generated from JSON and then filled in; runs every test.
matrix-sim:
	$(MAKE) -C src/examples/matrix_multiplier/tb_impl tests PYTHON="$(PYTHON)"
clean:
	$(MAKE) -C tests clean
	$(MAKE) -C src/examples/axi clean
	$(MAKE) -C src/examples/matrix_multiplier/tb_impl clean
