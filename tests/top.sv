`timescale 1ns/1ps
// A three-cycle pipeline, plus hierarchy for the interface path tests.
module sub #(parameter int ID = 0) (input logic valid);
  logic seen;
  assign seen = valid;
endmodule

module top #(parameter int WIDTH = 8, parameter int DEPTH = 3) (
  input  logic       clk,
  input  logic       rst_n,
  input  logic       s_valid_i,
  input  logic [7:0] s_data_i,
  output logic       m_valid_o,
  output logic [7:0] m_data_o
);
  logic       valid_q[0:1];
  logic [7:0] data_q[0:1];

  always_ff @(posedge clk) begin
    valid_q[0] <= s_valid_i;
    valid_q[1] <= valid_q[0];
    m_valid_o  <= valid_q[1];
    data_q[0]  <= s_data_i;
    data_q[1]  <= data_q[0];
    m_data_o   <= data_q[1];
  end

  sub #(.ID(1)) a(.valid(s_valid_i));
  sub #(.ID(2)) b(.valid(s_valid_i));

  for (genvar i = 0; i < 2; i++) begin : gen_blk
    sub u(.valid(s_valid_i));
  end
endmodule
