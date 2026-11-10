# Top-level entry points: compile, framework self-tests, and the AXI and matrix examples.
PYTHON ?= python
.PHONY: all test compile framework-test axi-verify axi-lint axi-sim matrix-sim generated clean
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
# The filled-in matrix testbench (tb_impl/); runs every test.
matrix-sim:
	$(MAKE) -C src/examples/matrix_multiplier sim PYTHON="$(PYTHON)"
# Rebuild each example's tb_generated/ from its tb/.
generated:
	$(MAKE) -C src/examples/matrix_multiplier generated PYTHON="$(PYTHON)"
	$(MAKE) -C src/examples/axi generated PYTHON="$(PYTHON)"
clean:
	$(MAKE) -C tests clean
	$(MAKE) -C src/examples/axi clean
	$(MAKE) -C src/examples/matrix_multiplier clean
