`timescale 1ns/1ps
// Quality-gate controls driving the baseline-derived dynamic frame overlay.
// Input/output frames are scheduled separately to model buffering delay, not a frame-ID binding.
module tb_quality_overlay;
    logic aclk=0; always #3.5 aclk=~aclk;
    logic aresetn=0;
    logic [23:0] s_axis_tdata=0;
    logic [2:0] s_axis_tkeep=7,s_axis_tstrb=7;
    logic s_axis_tuser=0,s_axis_tlast=0,s_axis_tvalid=0;
    wire s_axis_tready;
    logic [11:0] s_axi_awaddr=0,s_axi_araddr=0;
    logic [2:0] s_axi_awprot=0,s_axi_arprot=0;
    logic s_axi_awvalid=0,s_axi_wvalid=0,s_axi_bready=0,s_axi_arvalid=0,s_axi_rready=0;
    wire s_axi_awready,s_axi_wready,s_axi_bvalid,s_axi_arready,s_axi_rvalid;
    logic [31:0] s_axi_wdata=0;
    logic [3:0] s_axi_wstrb=15;
    wire [31:0] s_axi_rdata;
    wire [1:0] s_axi_bresp,s_axi_rresp,frame_state;
    wire capture_pending,roi_enable;
    wire [11:0] roi_x0,roi_y0,roi_x1,roi_y1;
    quality_gate_bd #(.FRAME_WIDTH(32),.FRAME_HEIGHT(24)) gate(.*);

    logic [23:0] display_data=24'h123456;
    logic display_user=0,display_last=0,display_valid=0,display_ready=1;
    wire input_ready,output_valid,output_user,output_last;
    wire [23:0] output_data;
    wire [2:0] output_keep,output_strb;
    axis_frame_overlay overlay(
        .aclk(aclk),.aresetn(aresetn),
        .s_axis_tdata(display_data),.s_axis_tkeep(3'b111),.s_axis_tstrb(3'b111),
        .s_axis_tuser(display_user),.s_axis_tlast(display_last),.s_axis_tvalid(display_valid),
        .s_axis_tready(input_ready),.m_axis_tdata(output_data),.m_axis_tkeep(output_keep),
        .m_axis_tstrb(output_strb),.m_axis_tuser(output_user),.m_axis_tlast(output_last),
        .m_axis_tvalid(output_valid),.m_axis_tready(display_ready),
        .overlay_enable(roi_enable),.frame_state(frame_state),
        .frame_x0(roi_x0),.frame_y0(roi_y0),.frame_x1(roi_x1),.frame_y1(roi_y1),.line_width(4'd4));

    integer checks=0;
    task automatic require(input bit good,input string label_text);
        if(!good) $fatal(1,"%s",label_text);
        checks++;
    endtask
    task automatic write_reg(input [11:0] address,input [31:0] value);
        fork
            begin
                @(negedge aclk);s_axi_awaddr=address;s_axi_awvalid=1;
                do @(posedge aclk); while(!s_axi_awready);
                @(negedge aclk);s_axi_awvalid=0;
            end
            begin
                @(negedge aclk);s_axi_wdata=value;s_axi_wvalid=1;
                do @(posedge aclk); while(!s_axi_wready);
                @(negedge aclk);s_axi_wvalid=0;
            end
        join
        while(!s_axi_bvalid) @(negedge aclk);
        require(s_axi_bresp===0,"AXI write response");
        s_axi_bready=1;@(negedge aclk);s_axi_bready=0;
    endtask
    task automatic input_frame(input bit bars);
        for(integer y=0;y<24;y++) for(integer x=0;x<32;x++) begin
            @(negedge aclk);s_axis_tvalid=1;
            s_axis_tuser=(x==0 && y==0);s_axis_tlast=(x==31);
            s_axis_tdata=bars ? ((x/2)%2 ? 24'hd0d0d0 : 24'h303030) : 24'hffffff;
        end
        @(negedge aclk);s_axis_tvalid=0;s_axis_tuser=0;s_axis_tlast=0;
        repeat(20) @(negedge aclk);
    endtask
    task automatic display_frame(input bit enabled,input [23:0] color,
        input integer x0,y0,w,h,input integer first_stall=1);
        bit border;
        logic [23:0] expected;
        for(integer y=0;y<24;y++) for(integer x=0;x<32;x++) begin
            @(negedge aclk);display_valid=1;
            display_user=(x==0 && y==0);display_last=(x==31);
            border=enabled && x>=x0 && x<x0+w && y>=y0 && y<y0+h
                && (x-x0<4 || x0+w-1-x<4 || y-y0<4 || y0+h-1-y<4);
            expected=border ? color : display_data;
            // Stall selected output pixels; quality side must stay always ready.
            if((x+3*y)%23==0) begin
                display_ready=0;
                repeat(x==0 && y==0 ? first_stall : 1) begin
                    @(posedge aclk);#1;
                    require(!input_ready && output_data===expected,"overlay stalled pixel");
                end
                @(negedge aclk);display_ready=1;
            end
            @(posedge aclk);
            require(output_valid && input_ready && output_data===expected,"overlay pixel/color/ROI");
            require(output_user===display_user && output_last===display_last
                && output_keep===7 && output_strb===7,"overlay sidebands");
        end
        @(negedge aclk);display_valid=0;display_user=0;display_last=0;
    endtask
    always @(posedge aclk) if(aresetn) require(s_axis_tready===1,"quality never backpressures input");
    initial begin
        repeat(4) @(negedge aclk);aresetn=1;
        display_frame(0,0,0,0,0,0);
        write_reg('h020,32'h00060008);write_reg('h024,32'h000c0010);
        write_reg('h028,32'hef10d228);write_reg('h02c,32'h00c800c8);
        write_reg('h030,32'h00020014);write_reg('h034,1);write_reg('h004,3);
        input_frame(0);require(frame_state===1,"bad exposure -> red");
        display_frame(1,24'h0000ff,8,6,16,12);
        input_frame(1);require(frame_state===2,"first good frame -> yellow");
        display_frame(1,24'h00ffff,8,6,16,12);
        input_frame(1);require(frame_state===3 && capture_pending,"N good frames -> green and request");
        display_frame(1,24'h00ff00,8,6,16,12);
        write_reg('h020,32'h00040004);write_reg('h024,32'h00100014);write_reg('h004,1);
        // APPLY alone cannot move the overlay: active ROI changes at input SOF.
        display_frame(1,24'h00ff00,8,6,16,12);
        // Change the active input ROI while an output frame is in progress.
        fork
            display_frame(1,24'h00ff00,8,6,16,12);
            begin repeat(80) @(negedge aclk);input_frame(1);end
        join
        require(frame_state===2 && roi_x0===4 && roi_y0===4,"new ROI starts new streak");
        display_frame(1,24'h00ffff,4,4,20,16);
        write_reg('h020,0);write_reg('h024,32'h00030003);write_reg('h004,1);input_frame(1);
        require(frame_state===2,"minimum top-left ROI");
        display_frame(1,24'h00ffff,0,0,3,3);
        write_reg('h020,32'h0015001d);write_reg('h004,1);
        // A new input ROI arrives while the first output pixel is stalled.
        // TDATA and the old frame's ROI must stay stable through the stall.
        fork
            display_frame(1,24'h00ffff,0,0,3,3,20);
            begin repeat(3) @(negedge aclk);input_frame(1);end
        join
        require(frame_state===2,"minimum bottom-right ROI");
        display_frame(1,24'h00ffff,29,21,3,3);
        write_reg('h034,0);write_reg('h004,1);input_frame(1);
        require(!roi_enable && frame_state===0,"disable clears valid state");
        display_frame(0,0,4,4,20,16);
        $display("PASS: quality controls + baseline overlay: %0d checks",checks);
        $finish;
    end
    initial begin #2000000;$fatal(1,"overlay simulation timeout");end
endmodule
