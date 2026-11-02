`timescale 1ns/1ps
// Round40 transport/control only. grouped_network and all arithmetic are frozen.
module cnn_accel_axi #(
 parameter integer INPUT_WORDS=16384,
 parameter integer CLOCK_HZ=80000000
)(
 (* X_INTERFACE_INFO="xilinx.com:signal:clock:1.0 aclk CLK", X_INTERFACE_PARAMETER="XIL_INTERFACENAME aclk, ASSOCIATED_BUSIF S_AXI:S_AXIS:M_AXIS, ASSOCIATED_RESET aresetn, FREQ_HZ 80000000" *) input aclk,
 (* X_INTERFACE_INFO="xilinx.com:signal:reset:1.0 aresetn RST", X_INTERFACE_PARAMETER="XIL_INTERFACENAME aresetn, POLARITY ACTIVE_LOW" *) input aresetn,
 (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI AWADDR", X_INTERFACE_PARAMETER="XIL_INTERFACENAME S_AXI, PROTOCOL AXI4LITE, DATA_WIDTH 32, ADDR_WIDTH 12, READ_WRITE_MODE READ_WRITE" *) input [11:0] s_axi_awaddr,
 (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI AWPROT" *) input [2:0] s_axi_awprot,
 (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI AWVALID" *) input s_axi_awvalid,
 (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI AWREADY" *) output s_axi_awready,
 (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI WDATA" *) input [31:0] s_axi_wdata,
 (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI WSTRB" *) input [3:0] s_axi_wstrb,
 (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI WVALID" *) input s_axi_wvalid,
 (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI WREADY" *) output s_axi_wready,
 (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI BRESP" *) output reg [1:0] s_axi_bresp,
 (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI BVALID" *) output reg s_axi_bvalid,
 (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI BREADY" *) input s_axi_bready,
 (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI ARADDR" *) input [11:0] s_axi_araddr,
 (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI ARPROT" *) input [2:0] s_axi_arprot,
 (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI ARVALID" *) input s_axi_arvalid,
 (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI ARREADY" *) output s_axi_arready,
 (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI RDATA" *) output reg [31:0] s_axi_rdata,
 (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI RRESP" *) output reg [1:0] s_axi_rresp,
 (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI RVALID" *) output reg s_axi_rvalid,
 (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI RREADY" *) input s_axi_rready,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 S_AXIS TDATA", X_INTERFACE_PARAMETER="XIL_INTERFACENAME S_AXIS, TDATA_NUM_BYTES 4, HAS_TKEEP 1, HAS_TLAST 1, HAS_TREADY 1" *) input [31:0] s_axis_tdata,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 S_AXIS TKEEP" *) input [3:0] s_axis_tkeep,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 S_AXIS TLAST" *) input s_axis_tlast,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 S_AXIS TVALID" *) input s_axis_tvalid,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 S_AXIS TREADY" *) output s_axis_tready,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 M_AXIS TDATA", X_INTERFACE_PARAMETER="XIL_INTERFACENAME M_AXIS, TDATA_NUM_BYTES 4, HAS_TKEEP 1, HAS_TLAST 1, HAS_TREADY 1" *) output [31:0] m_axis_tdata,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 M_AXIS TKEEP" *) output [3:0] m_axis_tkeep,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 M_AXIS TLAST" *) output m_axis_tlast,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 M_AXIS TVALID" *) output m_axis_tvalid,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 M_AXIS TREADY" *) input m_axis_tready
);
 reg aw_pending=0,w_pending=0;
 reg [11:0] aw_saved=0;reg [31:0] wd_saved=0;reg [3:0] ws_saved=0;
 reg busy=0,done_sticky=0,error_sticky=0,core_start=0;
 reg [3:0] reset_hold=15;
 reg [31:0] input_count=0,output_count=0,cycles=0,result_raw=0,frames=0,error_code=0;
 wire core_ready,core_idle,core_done,core_iready,core_ovalid;
 wire [15:0] core_odata;
 wire core_resetn=aresetn && (reset_hold==0);
 wire enabled=busy && !error_sticky && core_resetn;
 assign s_axis_tready=enabled && input_count<INPUT_WORDS && core_iready;
 assign m_axis_tdata={16'b0,core_odata};
 assign m_axis_tkeep=4'hf;assign m_axis_tlast=1'b1;
 assign m_axis_tvalid=enabled && output_count==0 && core_ovalid;
 wire input_hs=s_axis_tvalid && s_axis_tready;
 wire output_hs=m_axis_tvalid && m_axis_tready;
 grouped_network core(
  .ap_clk(aclk),.ap_rst_n(core_resetn),.ap_start(core_start),.ap_done(core_done),.ap_ready(core_ready),.ap_idle(core_idle),
  .x_TDATA(s_axis_tdata[23:0]),.x_TVALID(s_axis_tvalid && enabled && input_count<INPUT_WORDS),.x_TREADY(core_iready),
  .y_TDATA(core_odata),.y_TVALID(core_ovalid),.y_TREADY(enabled && output_count==0 && m_axis_tready));

 assign s_axi_awready=!aw_pending && !s_axi_bvalid;
 assign s_axi_wready=!w_pending && !s_axi_bvalid;
 assign s_axi_arready=!s_axi_rvalid;
 wire write_commit=aw_pending && w_pending && !s_axi_bvalid;
 wire start_allowed=!busy && reset_hold==0 && core_idle;
 wire write_ok=(aw_saved==12'h004) && (!ws_saved[0] ||
                ((wd_saved & 32'hfffffff8)==0 &&
                (!wd_saved[0] || wd_saved[1] || start_allowed) &&
                (!wd_saved[2] || wd_saved[1] || !busy)));
 wire command_valid=write_commit && write_ok && ws_saved[0];
 wire command_reset=command_valid && wd_saved[1];
 wire command_start=command_valid && wd_saved[0] && !wd_saved[1];
 wire command_clear=command_valid && wd_saved[2] && !wd_saved[1] && !wd_saved[0];
 function automatic [31:0] read_register(input [11:0] address);
  begin
   case(address)
    12'h000:read_register=32'h434e4e01;
    12'h004:read_register=0;
    12'h008:read_register={27'b0,(reset_hold!=0),core_idle,error_sticky,done_sticky,busy};
    12'h00c:read_register=input_count;
    12'h010:read_register=output_count;
    12'h014:read_register=cycles;
    12'h018:read_register=result_raw;
    12'h01c:read_register=frames;
    12'h020:read_register=error_code;
    12'h024:read_register=INPUT_WORDS;
    12'h028:read_register=CLOCK_HZ;
    default:read_register=0;
   endcase
  end
 endfunction
 always @(posedge aclk)begin
  if(!aresetn)begin
   aw_pending<=0;w_pending<=0;aw_saved<=0;wd_saved<=0;ws_saved<=0;
   s_axi_bvalid<=0;s_axi_bresp<=0;s_axi_rvalid<=0;s_axi_rresp<=0;s_axi_rdata<=0;
  end else begin
   if(s_axi_awvalid && s_axi_awready)begin aw_pending<=1;aw_saved<=s_axi_awaddr;end
   if(s_axi_wvalid && s_axi_wready)begin w_pending<=1;wd_saved<=s_axi_wdata;ws_saved<=s_axi_wstrb;end
   if(s_axi_bvalid && s_axi_bready)s_axi_bvalid<=0;
   if(write_commit)begin
    aw_pending<=0;w_pending<=0;s_axi_bvalid<=1;s_axi_bresp<=write_ok?2'b00:2'b10;
   end
   if(s_axi_rvalid && s_axi_rready)s_axi_rvalid<=0;
   if(s_axi_arvalid && s_axi_arready)begin
    s_axi_rvalid<=1;s_axi_rdata<=read_register(s_axi_araddr);
    s_axi_rresp<=((s_axi_araddr[1:0]==0)&&(s_axi_araddr<=12'h028))?2'b00:2'b10;
   end
  end
 end
 always @(posedge aclk)begin
  if(!aresetn)begin
   busy<=0;done_sticky<=0;error_sticky<=0;core_start<=0;reset_hold<=15;
   input_count<=0;output_count<=0;cycles<=0;result_raw<=0;frames<=0;error_code<=0;
  end else begin
   core_start<=0;
   if(reset_hold!=0)reset_hold<=reset_hold-1;
   if(command_reset)begin
    busy<=0;done_sticky<=0;error_sticky<=0;reset_hold<=15;
    input_count<=0;output_count<=0;cycles<=0;result_raw<=0;error_code<=0;
   end else if(command_start)begin
    busy<=1;done_sticky<=0;error_sticky<=0;core_start<=1;
    input_count<=0;output_count<=0;cycles<=0;result_raw<=0;error_code<=0;
   end else if(command_clear)begin done_sticky<=0;error_sticky<=0;error_code<=0;end
   else if(busy)begin
    cycles<=cycles+1;
    if(input_hs)input_count<=input_count+1;
    if(output_hs)begin output_count<=output_count+1;result_raw<={16'b0,core_odata};end
    if(core_done)begin
     busy<=0;
     if(input_count==INPUT_WORDS && (output_count==1 || output_hs))begin done_sticky<=1;frames<=frames+1;end
     else begin error_sticky<=1;error_code<=4;reset_hold<=15;end
    end
    if(input_hs && (s_axis_tlast!=(input_count==INPUT_WORDS-1) || s_axis_tkeep!=4'hf))begin
     busy<=0;error_sticky<=1;reset_hold<=15;
     error_code<={30'b0,(s_axis_tkeep!=4'hf),(s_axis_tlast!=(input_count==INPUT_WORDS-1))};
    end
   end
  end
 end
endmodule
