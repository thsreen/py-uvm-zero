# Testbench connections: tb.json

Generated from the JSON and agent template. If you edit agent/infra wiring manually, update this document too.

## Diagram

The testbench in UVM style: the test, TbEnv, and each agent with its stimuli, handler,
drivers, monitors, and scoreboards. Interfaces connect it to the DUT. The sections below give
every connection in detail.

```mermaid
flowchart TB
  subgraph n_test["Test: smoke"]
    subgraph n_tb_env["TbEnv"]
      n_clock["Clock agent"]
      n_reset["Reset agent"]
      subgraph n_agent_xbar["xbar agent"]
        n_st_xbar_smoke["XbarSmoke"]
        subgraph n_agent_xbar_initiator["initiator agent"]
          n_handler_xbar_initiator["Handler"]
          n_drv_xbar_initiator_req_driver["XbarInitiatorReqDriver"]
        end
        subgraph n_agent_xbar_target["target agent"]
          n_handler_xbar_target["Handler"]
          n_drv_xbar_target_resp_driver["XbarTargetRespDriver"]
        end
      end
    end
  end
  n_if_xbar_initiator_req[/"req interface"/]
  n_if_xbar_initiator_resp[/"resp interface"/]
  n_if_xbar_target_req[/"req interface"/]
  n_if_xbar_target_resp[/"resp interface"/]
  n_dut[["DUT"]]
  n_st_xbar_smoke --> n_handler_xbar_initiator
  n_st_xbar_smoke --> n_handler_xbar_target
  n_handler_xbar_initiator --> n_drv_xbar_initiator_req_driver
  n_drv_xbar_initiator_req_driver --> n_if_xbar_initiator_req
  n_handler_xbar_target --> n_drv_xbar_target_resp_driver
  n_drv_xbar_target_resp_driver --> n_if_xbar_target_resp
  n_if_xbar_initiator_req <--> n_dut
  n_if_xbar_initiator_resp <--> n_dut
  n_if_xbar_target_req <--> n_dut
  n_if_xbar_target_resp <--> n_dut
  n_clock --> n_dut
  n_reset --> n_dut
```

## Agent hierarchy

- TbEnv
  - clock (ClockAgent)
  - reset (ResetAgent)
  - xbar (XbarAgent)
    - initiator (XbarInitiatorAgent)
    - target (XbarTargetAgent)
    - reset (passive ResetAgent, owned by xbar)

## Tests

- `smoke` runs `XbarSmoke` (default)

## Components and connections by agent

### xbar

- Infrastructure: `xbar/agent/infra/xbar_agent.py`
- Connected module: `dut`
- Handler: `handler`, a queue per driver and every interface below
- Stimulus `smoke`: `XbarSmoke`, run by test smoke
- Child agent: `initiator`
- Child agent: `target`
- Child agent: `reset` (passive ResetAgent)

#### Connections

```text
TbEnv (test smoke) -> stimuli['smoke'].execute()
stimuli['smoke'].queue() -> initiator.handler queue -> initiator.req_driver
stimuli['smoke'].queue() -> target.handler queue -> target.resp_driver
```

### xbar.initiator

- Infrastructure: `xbar/agent/infra/xbar_initiator_agent.py`
- Connected module: `dut`
- Handler: `handler`, a queue per driver and every interface below
- Interface: `req` from `initiator_req.json`; observed values in `req.values`; transaction `XbarInitiatorReqTxn`; `clk` [Clock], `rst_n` [Reset]
- Interface: `resp` from `initiator_resp.json`; observed values in `resp.values`; transaction `XbarInitiatorRespTxn`; `clk` [Clock], `rst_n` [Reset]
- Driver `req_driver`: `XbarInitiatorReqDriver`, using `req`

#### Connections

```text
handler queue -> req_driver.drive() -> req signals -> DUT (writes only changes)
```

### xbar.target

- Infrastructure: `xbar/agent/infra/xbar_target_agent.py`
- Connected module: `dut`
- Handler: `handler`, a queue per driver and every interface below
- Interface: `req` from `target_req.json`; observed values in `req.values`; transaction `XbarTargetReqTxn`; `clk` [Clock], `rst_n` [Reset]
- Interface: `resp` from `target_resp.json`; observed values in `resp.values`; transaction `XbarTargetRespTxn`; `clk` [Clock], `rst_n` [Reset]
- Driver `resp_driver`: `XbarTargetRespDriver`, using `resp`

#### Connections

```text
handler queue -> resp_driver.drive() -> resp signals -> DUT (writes only changes)
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
ResetDriver -> reset -> dut.rst_ni
dut.rst_ni -> ResetMonitor -> reset.values
ResetMonitor -> ResetHandler.observe_reset
ResetHandler.wait_released -> TbEnv test stimulus
```

### xbar.reset

- Handler: `ResetHandler` (extends Handler)
- Interface: `reset`
- Monitor: `ResetMonitor`

#### Connections

```text
dut.rst_ni -> ResetMonitor -> reset.values
ResetMonitor -> ResetHandler.observe_reset
ResetMonitor -> parent.apply_reset / parent.release_reset
```
