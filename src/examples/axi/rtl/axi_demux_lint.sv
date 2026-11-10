module axi_demux_lint (
  input logic clk_i, rst_ni,
  input logic [$clog2(axi_demo_cfg_pkg::Targets)-1:0] aw_select_i, ar_select_i,
  input axi_demo_cfg_pkg::slv_req_t slv_req_i,
  output axi_demo_cfg_pkg::slv_resp_t slv_resp_o,
  output axi_demo_cfg_pkg::slv_req_t [axi_demo_cfg_pkg::Targets-1:0] mst_req_o,
  input axi_demo_cfg_pkg::slv_resp_t [axi_demo_cfg_pkg::Targets-1:0] mst_resp_i
);
  import axi_demo_cfg_pkg::*;
  axi_demux #(
    .AxiIdWidth(InitiatorIdWidth), .AxiLookBits(InitiatorIdWidth), .NoMstPorts(Targets),
    .aw_chan_t(slv_aw_chan_t), .w_chan_t(slv_w_chan_t), .b_chan_t(slv_b_chan_t),
    .ar_chan_t(slv_ar_chan_t), .r_chan_t(slv_r_chan_t),
    .axi_req_t(slv_req_t), .axi_resp_t(slv_resp_t)
  ) dut (
    .clk_i, .rst_ni, .slv_req_i, .slv_resp_o, .slv_aw_select_i(aw_select_i),
    .slv_ar_select_i(ar_select_i), .mst_reqs_o(mst_req_o), .mst_resps_i(mst_resp_i)
  );
endmodule
