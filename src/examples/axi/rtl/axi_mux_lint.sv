module axi_mux_lint (
  input logic clk_i, rst_ni,
  input axi_demo_cfg_pkg::slv_req_t [axi_demo_cfg_pkg::Initiators-1:0] slv_req_i,
  output axi_demo_cfg_pkg::slv_resp_t [axi_demo_cfg_pkg::Initiators-1:0] slv_resp_o,
  output axi_demo_cfg_pkg::mst_req_t mst_req_o,
  input axi_demo_cfg_pkg::mst_resp_t mst_resp_i
);
  import axi_demo_cfg_pkg::*;
  axi_mux #(
    .SlvAxiIDWidth(InitiatorIdWidth), .NoSlvPorts(Initiators),
    .slv_aw_chan_t(slv_aw_chan_t), .mst_aw_chan_t(mst_aw_chan_t), .w_chan_t(slv_w_chan_t),
    .slv_b_chan_t(slv_b_chan_t), .mst_b_chan_t(mst_b_chan_t),
    .slv_ar_chan_t(slv_ar_chan_t), .mst_ar_chan_t(mst_ar_chan_t),
    .slv_r_chan_t(slv_r_chan_t), .mst_r_chan_t(mst_r_chan_t),
    .slv_req_t(slv_req_t), .slv_resp_t(slv_resp_t), .mst_req_t(mst_req_t), .mst_resp_t(mst_resp_t)
  ) dut (.clk_i, .rst_ni, .slv_reqs_i(slv_req_i), .slv_resps_o(slv_resp_o), .mst_req_o, .mst_resp_i);
endmodule
