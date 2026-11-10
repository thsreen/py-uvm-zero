// Elaboration harness only: no traffic generation or behavioral replacement.
module axi_xbar_lint (
  input logic clk_i, rst_ni,
  input axi_demo_cfg_pkg::slv_req_t [axi_demo_cfg_pkg::Initiators-1:0] slv_req_i,
  output axi_demo_cfg_pkg::slv_resp_t [axi_demo_cfg_pkg::Initiators-1:0] slv_resp_o,
  output axi_demo_cfg_pkg::mst_req_t [axi_demo_cfg_pkg::Targets-1:0] mst_req_o,
  input axi_demo_cfg_pkg::mst_resp_t [axi_demo_cfg_pkg::Targets-1:0] mst_resp_i
);
  import axi_demo_cfg_pkg::*;
  axi_pkg::xbar_rule_32_t [Targets-1:0] address_map;
  for (genvar i = 0; i < Targets; i++) begin : gen_address_map
    // Four non-overlapping 64 KiB target windows at 0x0000_0000..0x0003_ffff.
    assign address_map[i] = '{idx: 32'(i), start_addr: 32'(i * 32'h10000), end_addr: 32'((i+32'd1) * 32'h10000)};
  end
  axi_xbar #(
    .Cfg(XbarCfg), .ATOPs(1'b1),
    .slv_aw_chan_t(slv_aw_chan_t), .mst_aw_chan_t(mst_aw_chan_t), .w_chan_t(slv_w_chan_t),
    .slv_b_chan_t(slv_b_chan_t), .mst_b_chan_t(mst_b_chan_t),
    .slv_ar_chan_t(slv_ar_chan_t), .mst_ar_chan_t(mst_ar_chan_t),
    .slv_r_chan_t(slv_r_chan_t), .mst_r_chan_t(mst_r_chan_t),
    .slv_req_t(slv_req_t), .slv_resp_t(slv_resp_t),
    .mst_req_t(mst_req_t), .mst_resp_t(mst_resp_t), .rule_t(axi_pkg::xbar_rule_32_t)
  ) dut (
    .clk_i, .rst_ni, .slv_ports_req_i(slv_req_i), .slv_ports_resp_o(slv_resp_o),
    .mst_ports_req_o(mst_req_o), .mst_ports_resp_i(mst_resp_i), .addr_map_i(address_map),
    .en_default_mst_port_i('0), .default_mst_port_i('0)
  );
endmodule
