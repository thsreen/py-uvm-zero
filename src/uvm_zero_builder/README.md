# uvm_zero_builder: the generator

`uvm_zero_builder` turns a testbench description in JSON into the files a
[`uvm_zero_base`](../uvm_zero_base/README.md) testbench needs: agent wiring,
protocol skeletons, typed transaction classes, stimuli, a Makefile and a diagram.
It checks the description first and never overwrites code you have written.

Back to the [project overview](../../README.md).

## Files

| File | Holds |
| --- | --- |
| `plan.py` | Reads and checks `tb.json` and its interface files; builds the agent tree (`load_plan`). |
| `generate.py` | Writes the files below; the `uvm-zero-generate` command. |
| `diagram.py` | Lays out, audits and draws `tb_diagram.svg`. |
| `templates/agent.py.tmpl` | The agent infrastructure template. |
| `templates/Makefile.tmpl` | The generated Makefile. |

## Running it

```sh
uvm-zero-generate path/to/tb.json --check           # validate; list what would be written
uvm-zero-generate path/to/tb.json                   # write every missing file
uvm-zero-generate path/to/tb.json --check --refresh-infra
uvm-zero-generate path/to/tb.json --refresh-infra   # also replace infra, the diagram and the Makefile
```

Everything is written next to `tb.json`. The command also lists class files the
JSON no longer names, and every callback an existing class still lacks after a
connection was added.

| Output | Written | Yours to edit |
| --- | --- | --- |
| `<agent>/agent/infra/<agent>_agent.py` | When missing, or with `--refresh-infra` | Yes, but a refresh replaces it |
| `<agent>/agent/*_driver.py`, `*_monitor.py`, `*_scoreboard.py` | When missing | Yes: the protocol |
| `<agent>/agent/*_txn.py` | When missing | Yes |
| `<agent>/seqs/*.py` | When missing | Yes: the scenarios |
| `tb_diagram.svg` | When missing, or with `--refresh-infra` | No |
| `Makefile` | When missing, or with `--refresh-infra` | Yes, but a refresh replaces it |

After a topology change (a new interface, component or connection), preview with
`--check --refresh-infra`, then refresh. Add any new callbacks the command lists to
your existing classes. `TbEnv` imports the generated agent classes; it does not
build protocol agents from JSON while simulating, so run the generator before
using a new config.

## tb.json

```json
{
  "simulation": {
    "toplevel": "matrix_multiplier",
    "sources": ["../rtl/matrix_multiplier.sv"],
    "simulator": "verilator",
    "tests": {"smoke": "MatMulTraffic"}
  },
  "clock": {"signal": "dut.clk_i", "period_ns": 10},
  "reset": {"signal": "dut.reset_i", "active_high": true, "duration_factor": 2},
  "mat_mul": {
    "connected_module": "dut",
    "ip": "interfaces/input.json",
    "op": "interfaces/output.json",
    "driver": ["MatMulIpDriver"],
    "monitor": ["MatMulIpMonitor", "MatMulOpMonitor"],
    "scoreboard": "MatMulScoreboard",
    "stimulus": "MatMulTraffic",
    "connections": ["MatMulIpMonitor -> MatMulScoreboard", "MatMulOpMonitor -> MatMulScoreboard"]
  },
  "settings": {"timeout": 100, "timeout_unit": "us", "drain_cycles": 3}
}
```

Top-level keys:

| Key | Meaning |
| --- | --- |
| `simulation` | How to build and run the DUT; see [The Makefile](#the-makefile). |
| `clock` | `signal`, `period_ns`; `active: false` for a passive clock with optional `check_period`. |
| `reset` | `signal`, `active_high`, `period_ns`, `duration_factor`, `restart_sequence`. |
| `settings` | Environment settings: timeout, heartbeat, drain, error limit. |
| any other key | A top-level agent of that name. |

Within each agent object:

| Key | Value |
| --- | --- |
| `driver`, `monitor`, `scoreboard` | One class name, `true` for the base class, `false` or absent for none, or a list of class names. |
| `stimulus` | Registered stimuli: one class name, `true`, or a list. |
| `connections` | `["<SourceClass> -> <TargetClass>", ...]`, the only routes between components. |
| `connected_module` | The DUT module the agent's signals are relative to; `.child` extends the parent's. |
| `active` | `false` for a passive agent, without drivers or stimuli. |
| any key holding a string | An interface file. |
| any key holding an object | A child agent; `port[N]` makes an array, with `{i}` the nearest array's index. |

### Components and naming

Class names follow the agent hierarchy: drivers, monitors and scoreboards of
`demo.port` start with `DemoPort`, and stimuli start with the agent's own prefix
(`DemoTraffic`). Each agent gets its own infrastructure file; array instances share
their class files.

A single driver or monitor is keyed `driver` or `monitor` and uses every interface
in the agent and below. In a list, each class's hint names its interface:
`MatMulIpMonitor` is `ip_monitor` and watches only `ip`. A listed scoreboard is
keyed by its hint alone (`MatMulCheckScoreboard` is `check_scoreboard`), and a
stimulus always is (`MatMulTraffic` is `stimuli["traffic"]`).

### Connections

```json
"connections": [
  "MatMulIpMonitor -> MatMulCheckScoreboard",
  "MatMulOpMonitor -> MatMulCheckScoreboard",
  "MatMulCheckScoreboard -> MatMulSummaryScoreboard",
  "MatMulCheckScoreboard -> MatMulTraffic"
]
```

Connections name classes from the declaring agent and the agents below it, so a
`true` component, which has no class, cannot be connected. The target receives
items at `on_<source>_callback`, named from where the source sits in the declaring
agent: `MatMulIpMonitor` gives `on_ip_monitor_callback`, and a child agent `aw`'s
monitor gives `on_aw_monitor_callback`. A source class used by an array connects
every instance to one callback named after the array (`on_slave_monitor_callback`),
which receives the instance indices first. A target class needs exactly one
instance where the connection is declared; for per-instance wiring, declare the
connection inside the array's own object. The check reports malformed entries,
unknown classes, duplicates, ambiguous targets and clashing callback names.

## Interface files

```json
{
  "signals": [".clk_i -> clk [Clock]", ".reset_i -> reset [Reset]", ".valid_i -> valid", ".a_i -> a", ".b_i -> b"],
  "parameters": [".DATA_WIDTH -> DATA_WIDTH", ".A_ROWS -> A_ROWS"]
}
```

An interface lists only the DUT signals the testbench needs. `.valid` is relative
to the agent's `connected_module`; `dut.core.valid` is rooted at the DUT. `->`
renames a handle. A reference such as `{"interface": "lower.json",
"connected_module": "dut.core"}` relocates a shared definition. Missing DUT paths
fail during construction.

Tag clock and reset signals with `[Clock]` and `[Reset]`, one space after the
entry. Tagged signals are not transaction fields, clocks are not sampled into
`values`, and generated skeletons wait on the tagged clock.

Module parameters are not signals. List them under `parameters`, with the same
path and rename syntax. Each is read once from the elaborated DUT and becomes a
plain constant, as in RTL. A parameter listed under `signals`, or a signal under
`parameters`, is an error. Verilator exposes only public parameters, for example
with `/*verilator public_flat_rd*/`.

## Transaction classes

The generator writes one `Transaction` subclass per interface, named
`<features><Interface>Txn`, with a field for every signal that is neither tagged
nor a parameter:

```python
@dataclass
class MatMulIpTxn(Transaction):
    valid: object = None
    a: object = None
    b: object = None

    @classmethod
    def idle_values(cls):
        return {"valid": 0, "a": 0, "b": 0}
```

```python
self.publish_ip(MatMulIpTxn.from_values(self.interfaces["ip"].values))    # monitor
self.drive_values(**txn.signal_values())                                  # driver: fields that are set
self.drive_values(**MatMulIpTxn.idle_values())                            # driver: drive_idle()
self.queue(MatMulIpTxn(valid=1, a=a, b=b), driver="ip_driver")            # stimulus
```

Generated code is typed with these classes: `drive(self, txn: MatMulIpTxn)`,
`publish_ip(self, txn: MatMulIpTxn)`, and every callback fed by a monitor or a
driver. A component spanning several interfaces, and a callback fed by a
scoreboard or stimulus, take an untyped `txn`. Signal names `source`, `sequence`,
`driver` and `instance_id` would clash with `Transaction`'s routing attributes,
so the check rejects them; rename such a signal with `->`.

## The Makefile

The `simulation` section tells the generator how to build the DUT:

| Key | Meaning |
| --- | --- |
| `toplevel` | The DUT's top module. |
| `sources` | RTL files, relative to `tb.json`. |
| `simulator` | The default `SIM`; `verilator` unless set. |
| `parameters` | DUT parameter values set at elaboration, like `#(...)` on an RTL instance. |
| `compile_args` | Extra simulator compile arguments. |
| `tests` | Test names mapped to registered stimulus classes. |

```sh
make                 # the first test in simulation.tests
make smoke           # one test; same as make TB_TEST=smoke
make tests           # every test, one simulation and results file each
make SIM=icarus      # another simulator
make generate        # check the config and write missing classes
```

The Makefile reads the test names from `tb.json` each time it runs, so adding or
renaming tests needs no new Makefile. Parameters reach each simulator through its
own option (`-G`, `-P`, `-g`, `-defparam`, `-pvalue+`), and the testbench reads
the elaborated values back, so the DUT stays the single source of truth.

## The diagram

`tb_diagram.svg` is drawn from the JSON in a fixed UVM style: the DUT in the
centre, input interfaces on its left (those a driver drives) and outputs on its
right, active agents above and passive agents below. Wires are schematic nets: one
trunk per group of connections, with a dot where a branch joins. The clock and
reset agents are tried in every position in both rows, and the arrangement with
the fewest crossings wins.

Every drawing audits itself (`diagram.check()`). It reports a wire through a
component, wires of different connections lying on top of each other, overlapping
boxes, and a connection that doesn't join up, misses an end or lacks its arrow. The
generator prints these as warnings, and the framework tests fail on them and cap
each example's crossings, so a messier layout is caught without anyone looking at
it. `python -m uvm_zero_builder.diagram docs/architecture.svg` redraws the
project's generic diagram.
