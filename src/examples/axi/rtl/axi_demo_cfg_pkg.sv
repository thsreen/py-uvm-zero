// Local elaboration configuration. Upstream RTL is kept unchanged.
`include "axi/typedef.svh"
package axi_demo_cfg_pkg;
  localparam int unsigned Initiators = 4;
  localparam int unsigned Targets = 4;
  localparam int unsigned AddrWidth = 32;
  localparam int unsigned DataWidth = 64;
  localparam int unsigned InitiatorIdWidth = 4;
  localparam int unsigned TargetIdWidth = InitiatorIdWidth + $clog2(Initiators);
  typedef logic [AddrWidth-1:0] addr_t;
  typedef logic [DataWidth-1:0] data_t;
  typedef logic [DataWidth/8-1:0] strb_t;
  typedef logic [InitiatorIdWidth-1:0] slv_id_t;
  typedef logic [TargetIdWidth-1:0] mst_id_t;
  typedef logic [0:0] user_t;
  `AXI_TYPEDEF_ALL(slv, addr_t, slv_id_t, data_t, strb_t, user_t)
  `AXI_TYPEDEF_ALL(mst, addr_t, mst_id_t, data_t, strb_t, user_t)
  localparam axi_pkg::xbar_cfg_t XbarCfg = '{
    NoSlvPorts: 32'(Initiators), NoMstPorts: 32'(Targets),
    MaxMstTrans: 32'd8, MaxSlvTrans: 32'd8,
    FallThrough: 1'b0, LatencyMode: axi_pkg::CUT_ALL_AX, PipelineStages: 32'd1,
    AxiIdWidthSlvPorts: 32'(InitiatorIdWidth), AxiIdUsedSlvPorts: 32'(InitiatorIdWidth),
    UniqueIds: 1'b0, AxiAddrWidth: 32'(AddrWidth), AxiDataWidth: 32'(DataWidth), NoAddrRules: 32'(Targets)
  };
endpackage
