`timescale 1ns/1ps
// DMA-side stimulus + actual frozen CNN. Distinct from the protocol stub.
module real_core_tb;
 reg clk=0;always #6.25 clk=~clk;
 reg rst=0;reg[11:0] awaddr=0,araddr=0;
 reg awvalid=0,wvalid=0,bready=0,arvalid=0,rready=0;
 reg[31:0] wdata=0;wire awready,wready,bvalid,arready,rvalid;
 wire[1:0] bresp,rresp;wire[31:0] rdata;
 reg[31:0] sd=0;reg sl=0,sv=0,mr=0;
 wire sr,mv,ml;wire[31:0] md;wire[3:0] mk;
 cnn_accel_axi dut(
 .aclk(clk),.aresetn(rst),
 .s_axi_awaddr(awaddr),.s_axi_awprot(3'b0),.s_axi_awvalid(awvalid),.s_axi_awready(awready),
 .s_axi_wdata(wdata),.s_axi_wstrb(4'hf),.s_axi_wvalid(wvalid),.s_axi_wready(wready),
 .s_axi_bresp(bresp),.s_axi_bvalid(bvalid),.s_axi_bready(bready),
 .s_axi_araddr(araddr),.s_axi_arprot(3'b0),.s_axi_arvalid(arvalid),.s_axi_arready(arready),
 .s_axi_rdata(rdata),.s_axi_rresp(rresp),.s_axi_rvalid(rvalid),.s_axi_rready(rready),
 .s_axis_tdata(sd),.s_axis_tkeep(4'hf),.s_axis_tlast(sl),.s_axis_tvalid(sv),.s_axis_tready(sr),
 .m_axis_tdata(md),.m_axis_tkeep(mk),.m_axis_tlast(ml),.m_axis_tvalid(mv),.m_axis_tready(mr));
 task tick;begin @(posedge clk);#1;end endtask
 task wr(input[31:0] v);begin
  @(negedge clk);awaddr=4;awvalid=1;
  do @(posedge clk);while(!awready);
  @(negedge clk);awvalid=0;wdata=v;wvalid=1;
  do @(posedge clk);while(!wready);
  @(negedge clk);wvalid=0;bready=1;
  do @(posedge clk);while(!bvalid);
  if(bresp!==0)$fatal(1,"AXI write failure %h",bresp);
  @(negedge clk);bready=0;
 end endtask
 task rd(input[11:0] a,output[31:0] v);begin
  @(negedge clk);araddr=a;arvalid=1;
  do @(posedge clk);while(!arready);
  @(negedge clk);arvalid=0;rready=1;
  do @(posedge clk);while(!rvalid);
  if(rresp!==0)$fatal(1,"AXI read failure");v=rdata;
  @(negedge clk);rready=0;
 end endtask
 reg[23:0] inputs[0:65535];reg[15:0] expected[0:3];
 integer frame,sent,cycle,held,accepted;reg[31:0] observed,value,blocked;
 initial begin
  $readmemh("input.hex",inputs);$readmemh("expected.hex",expected);
  repeat(10)tick();@(negedge clk);rst=1;repeat(25)tick();
  for(frame=0;frame<4;frame=frame+1)begin
   wr(1);sent=0;cycle=0;held=0;observed=0;mr=0;sv=0;
   while(!observed)begin
    @(posedge clk);cycle=cycle+1;accepted=sv&&sr;
    if(accepted)sent=sent+1;
    if(mv && !mr)begin
     if(held>0 && md!==blocked)$fatal(1,"Actual core output unstable");
     blocked=md;held=held+1;
    end
    if(mv && mr)begin
     if(md!=={16'b0,expected[frame]} || mk!==15 || !ml)$fatal(1,"Golden bridge mismatch frame=%0d got=%h",frame,md);
     observed=1;
    end
    if(cycle%1000000==0)$display("SYSTEM_CORE_PROGRESS frame=%0d cycles=%0d sent=%0d",frame,cycle,sent);
    if(cycle>16000000)$fatal(1,"Actual core timeout frame=%0d sent=%0d",frame,sent);
    @(negedge clk);
    if(!sv || accepted)begin
     sv=sent<16384 && cycle%23!=0;
     if(sent<16384)begin sd={8'b0,inputs[frame*16384+sent]};sl=(sent==16383);end
    end
    mr=held>=11;
   end
   sv=0;repeat(12)tick();rd(8,value);
   if(value[2:0]!==3'b010)$fatal(1,"Bad completion status %h",value);
   rd('h0c,value);if(value!==16384)$fatal(1,"Actual input count");
   rd('h10,value);if(value!==1)$fatal(1,"Actual output count");
   rd('h18,value);if(value!=={16'b0,expected[frame]})$fatal(1,"Actual result mirror");
   rd('h1c,value);if(value!==frame+1)$fatal(1,"Actual frame counter");
   $display("SYSTEM_CORE_FRAME_PASS frame=%0d input_words=%0d raw=%h cycles=%0d stalls=%0d",frame,sent,expected[frame],cycle,held);
  end
  $display("SYSTEM_CORE_GOLDEN_PASS frames=4 mismatches=0 reset_between_frames=0");$finish;
 end
endmodule
