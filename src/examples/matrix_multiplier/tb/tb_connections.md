# Testbench connections: tb.json

Generated from the JSON and agent template. If you edit agent/infra wiring manually, update this document too.

## Diagram

Agents are boxes; parallelograms are interfaces, labelled with their Txn class. Arrows follow
the items: stimulus, handler queue, driver, interface, DUT, monitor, then each JSON connection,
labelled with the callback it calls. Dotted arrows show tests and resets.

```mermaid
flowchart LR
  n_dut[["DUT"]]
  subgraph n_tb_env["TbEnv"]
    n_clock["clock<br/>ClockAgent"]
    n_reset["reset<br/>ResetAgent"]
    subgraph n_agent_mat_mul["mat_mul : MatMulAgent"]
      n_handler_mat_mul[("handler")]
      n_if_mat_mul_ip[/"ip<br/>MatMulIpTxn"/]
      n_if_mat_mul_op[/"op<br/>MatMulOpTxn"/]
      n_mon_mat_mul_ip_monitor["ip_monitor<br/>MatMulIpMonitor"]
      n_mon_mat_mul_op_monitor["op_monitor<br/>MatMulOpMonitor"]
      n_drv_mat_mul_ip_driver["ip_driver<br/>MatMulIpDriver"]
      n_sb_mat_mul_scoreboard["scoreboard<br/>MatMulScoreboard"]
      n_st_mat_mul_traffic["traffic<br/>MatMulTraffic"]
    end
  end
  n_drv_mat_mul_ip_driver -->|drive_values| n_if_mat_mul_ip
  n_handler_mat_mul -->|pop| n_drv_mat_mul_ip_driver
  n_if_mat_mul_ip -->|values| n_mon_mat_mul_ip_monitor
  n_if_mat_mul_ip <-->|signals| n_dut
  n_if_mat_mul_op -->|values| n_mon_mat_mul_op_monitor
  n_if_mat_mul_op <-->|signals| n_dut
  n_mon_mat_mul_ip_monitor -->|on_ip_monitor_callback| n_sb_mat_mul_scoreboard
  n_mon_mat_mul_op_monitor -->|on_op_monitor_callback| n_sb_mat_mul_scoreboard
  n_st_mat_mul_traffic -->|queue| n_handler_mat_mul
  n_clock -->|clock| n_dut
  n_reset -->|reset| n_dut
  n_reset -.->|resets| n_agent_mat_mul
  n_test_smoke(["test smoke"])
  n_test_smoke -.->|runs| n_st_mat_mul_traffic
```

## Agent hierarchy

- TbEnv
  - clock (ClockAgent)
  - reset (ResetAgent)
  - mat_mul (MatMulAgent)
    - reset (passive ResetAgent, owned by mat_mul)

## Tests

- `smoke` runs `MatMulTraffic` (default)

## Components and connections by agent

### mat_mul

- Infrastructure: `mat_mul/agent/infra/mat_mul_agent.py`
- Connected module: `dut`
- Handler: `handler`, a queue per driver and every interface below
- Interface: `ip` from `input.json`; observed values in `ip.values`; transaction `MatMulIpTxn`; `clk` [Clock], `reset` [Reset]
- Interface: `op` from `output.json`; observed values in `op.values`; transaction `MatMulOpTxn`; `clk` [Clock], `reset` [Reset]
- Monitor `ip_monitor`: `MatMulIpMonitor`, using `ip`
- Monitor `op_monitor`: `MatMulOpMonitor`, using `op`
- Driver `ip_driver`: `MatMulIpDriver`, using `ip`
- Scoreboard `scoreboard`: `MatMulScoreboard`
- Stimulus `traffic`: `MatMulTraffic`, run by test smoke
- Child agent: `reset` (passive ResetAgent)

#### Connections

```text
TbEnv (test smoke) -> stimuli['traffic'].execute()
stimuli['traffic'].queue() -> handler queue -> ip_driver
handler queue -> ip_driver.drive() -> ip signals -> DUT (writes only changes)
DUT -> ip signals -> ip_monitor.publish_ip() -> ip.values
DUT -> op signals -> op_monitor.publish_op() -> op.values
ip_monitor (MatMulIpMonitor) -> scoreboard.on_ip_monitor_callback (scoreboard.callback: history, heartbeat)
op_monitor (MatMulOpMonitor) -> scoreboard.on_op_monitor_callback (scoreboard.callback: history, heartbeat)
```

### clock

- Interface: `clock`
- Monitor: `Monitor`
- Driver: `ClockDriver`

#### Connections

```text
ClockDriver -> clock -> dut.clk_i
dut.clk_i -> monitor -> clock.values
clock -> TbEnv heartbeat_clock
```

### reset

- Handler: `ResetHandler` (extends Handler)
- Interface: `reset`
- Monitor: `ResetMonitor`
- Driver: `ResetDriver`

#### Connections

```text
ResetDriver -> reset -> dut.reset_i
dut.reset_i -> ResetMonitor -> reset.values
ResetMonitor -> ResetHandler.observe_reset
ResetHandler.wait_released -> TbEnv test stimulus
```

### mat_mul.reset

- Handler: `ResetHandler` (extends Handler)
- Interface: `reset`
- Monitor: `ResetMonitor`

#### Connections

```text
dut.reset_i -> ResetMonitor -> reset.values
ResetMonitor -> ResetHandler.observe_reset
ResetMonitor -> parent.apply_reset / parent.release_reset
```
