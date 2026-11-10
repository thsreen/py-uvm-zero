# Shared infrastructure. The example Makefile supplies the DUT and TB choices.
PYTHON ?= python
COCOTB_TEST_MODULES ?= uvm_zero_base.test
# The base TbEnv suits a TB_CONFIG-only testbench; examples name their own.
TB_ENV ?= uvm_zero_base:TbEnv
TB_ENV_NAME ?= tb_env
TB_SEQUENCE ?=
TB_TEST ?=
TB_ENV_CONFIG ?=
TB_SEQUENCE_CONFIG ?=
TB_INTERFACE_CONFIG ?=
TB_CONFIG ?=

# Export selectors and constructor options to the Python cocotb process.
export TB_ENV TB_ENV_NAME TB_SEQUENCE TB_TEST TB_ENV_CONFIG TB_SEQUENCE_CONFIG TB_INTERFACE_CONFIG TB_CONFIG

include $(shell $(PYTHON) -m cocotb_tools.config --makefiles)/Makefile.sim

# Run each sequence in TB_REGRESS as its own simulation; report any failure at the end.
TB_REGRESS ?= $(TB_SEQUENCE)
.PHONY: regress
regress:
	@status=0; for sequence in $(TB_REGRESS); do \
		$(MAKE) -f $(firstword $(MAKEFILE_LIST)) sim TB_SEQUENCE=$$sequence \
			COCOTB_RESULTS_FILE=results_$$(echo $$sequence | tr ':.' '__').xml || status=1; \
	done; exit $$status

# Check TB_CONFIG and write skeletons for the classes it names; never overwrites.
.PHONY: generate
generate:
	$(PYTHON) -m uvm_zero_builder.generate $(TB_CONFIG)
