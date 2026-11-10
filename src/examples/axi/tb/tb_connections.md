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
    subgraph n_agent_xbar["xbar : XbarAgent"]
      n_handler_xbar[("handler")]
      n_st_xbar_smoke["smoke<br/>XbarSmoke"]
      subgraph n_agent_xbar_initiator["initiator : XbarInitiatorAgent"]
        n_handler_xbar_initiator[("handler")]
        n_if_xbar_initiator_req[/"req<br/>XbarInitiatorReqTxn"/]
        n_if_xbar_initiator_resp[/"resp<br/>XbarInitiatorRespTxn"/]
        n_drv_xbar_initiator_req_driver["req_driver<br/>XbarInitiatorReqDriver"]
      end
      subgraph n_agent_xbar_target["target : XbarTargetAgent"]
        n_handler_xbar_target[("handler")]
        n_if_xbar_target_req[/"req<br/>XbarTargetReqTxn"/]
        n_if_xbar_target_resp[/"resp<br/>XbarTargetRespTxn"/]
        n_drv_xbar_target_resp_driver["resp_driver<br/>XbarTargetRespDriver"]
      end
    end
  end
  n_drv_xbar_initiator_req_driver -->|drive_values| n_if_xbar_initiator_req
  n_drv_xbar_target_resp_driver -->|drive_values| n_if_xbar_target_resp
  n_handler_xbar_initiator -->|pop| n_drv_xbar_initiator_req_driver
  n_handler_xbar_target -->|pop| n_drv_xbar_target_resp_driver
  n_if_xbar_initiator_req <-->|signals| n_dut
  n_if_xbar_initiator_resp <-->|signals| n_dut
  n_if_xbar_target_req <-->|signals| n_dut
  n_if_xbar_target_resp <-->|signals| n_dut
  n_st_xbar_smoke -->|queue| n_handler_xbar_initiator
  n_st_xbar_smoke -->|queue| n_handler_xbar_target
  n_clock -->|clock| n_dut
  n_reset -->|reset| n_dut
  n_reset -.->|resets| n_agent_xbar
  n_test_smoke(["test smoke"])
  n_test_smoke -.->|runs| n_st_xbar_smoke
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
