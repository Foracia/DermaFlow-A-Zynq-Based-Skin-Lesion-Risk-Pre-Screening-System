`timescale 1ns/1ps
module tb_quality_gate_axi;
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
    logic [3:0] s_axi_wstrb=0;
    wire [31:0] s_axi_rdata;
    wire [1:0] s_axi_bresp,s_axi_rresp,frame_state;
    wire capture_pending;
    wire roi_enable;
    wire [11:0] roi_x0,roi_y0,roi_x1,roi_y1;
    quality_gate_bd #(.FRAME_WIDTH(8),.FRAME_HEIGHT(6)) dut(.*);
    integer checks=0, dump;
    logic [31:0] value;
    task automatic check_equal(input [31:0] actual,expected,input string label_text);
        if(actual !== expected) $fatal(1,"%s actual=%h expected=%h",label_text,actual,expected);
        checks=checks+1;
    endtask
    task automatic axi_write(input [11:0] address,input [31:0] data,
        input [3:0] strobes=15,input integer order=0,input [1:0] response=0);
        fork
            begin
                if(order==2) repeat(5) @(negedge aclk);
                @(negedge aclk);s_axi_awaddr=address;s_axi_awvalid=1;
                do @(posedge aclk); while(!s_axi_awready);
                @(negedge aclk);s_axi_awvalid=0;
            end
            begin
                if(order==1) repeat(5) @(negedge aclk);
                @(negedge aclk);s_axi_wdata=data;s_axi_wstrb=strobes;s_axi_wvalid=1;
                do @(posedge aclk); while(!s_axi_wready);
                @(negedge aclk);s_axi_wvalid=0;
            end
        join
        while(!s_axi_bvalid) @(negedge aclk);
        check_equal({30'd0,s_axi_bresp},{30'd0,response},"BRESP");
        repeat(3) begin
            @(negedge aclk);
            check_equal({31'd0,s_axi_bvalid},1,"BVALID held");
            check_equal({30'd0,s_axi_bresp},{30'd0,response},"BRESP held");
            check_equal({31'd0,s_axi_awready},0,"AW blocked behind response");
            check_equal({31'd0,s_axi_wready},0,"W blocked behind response");
        end
        s_axi_bready=1;@(negedge aclk);s_axi_bready=0;
    endtask
    task automatic axi_read(input [11:0] address,output [31:0] data,input [1:0] response=0);
        @(negedge aclk);s_axi_araddr=address;s_axi_arvalid=1;
        do @(posedge aclk); while(!s_axi_arready);
        @(negedge aclk);s_axi_arvalid=0;
        while(!s_axi_rvalid) @(negedge aclk);
        data=s_axi_rdata;
        check_equal({30'd0,s_axi_rresp},{30'd0,response},"RRESP");
        repeat(3) begin
            @(negedge aclk);
            check_equal({31'd0,s_axi_rvalid},1,"RVALID held");
            check_equal(s_axi_rdata,data,"RDATA held");
            check_equal({30'd0,s_axi_rresp},{30'd0,response},"RRESP held");
        end
        s_axi_rready=1;@(negedge aclk);s_axi_rready=0;
    endtask
    task automatic read_expect(input [11:0] address,input [31:0] expected);
        logic [31:0] data;
        axi_read(address,data);check_equal(data,expected,"register read");
    endtask
    task automatic send_frame(input bit white_frame=0);
        for(integer y=0;y<6;y=y+1) begin
            for(integer x=0;x<8;x=x+1) begin
                @(negedge aclk);s_axis_tvalid=1;
                s_axis_tuser=(x==0 && y==0);s_axis_tlast=(x==7);
                s_axis_tdata=white_frame ? 24'hffffff : x<4 ? 24'h303030 : 24'hd0d0d0;
            end
        end
        @(negedge aclk);s_axis_tvalid=0;s_axis_tuser=0;s_axis_tlast=0;
        repeat(12) @(negedge aclk);
    endtask
    always @(posedge aclk) begin
        #1;if(s_axis_tready !== 1) $fatal(1,"AXI traffic must not backpressure video");
    end
    initial begin
        repeat(4) @(negedge aclk);aresetn=1;
        read_expect(12'h000,32'h51475402);
        read_expect(12'h01c,32'h00060008);
        axi_write(12'h004,4);read_expect(12'h044,0);read_expect(12'h014,1);
        axi_write(12'h020,0,15,1);
        axi_write(12'h020,32'haabbccdd,1,2);read_expect(12'h020,32'h000000dd);
        axi_write(12'h020,32'haabbccdd,4);read_expect(12'h020,32'h00bb00dd);
        axi_write(12'h004,3,0);read_expect(12'h008,0);
        axi_write(12'h004,8,15,0,2);read_expect(12'h008,0);
        axi_write(12'h000,0,15,0,2);
        axi_write(12'h021,0,15,0,2);
        axi_read(12'h001,value,2);axi_read(12'h120,value,2);
        axi_write(12'h020,0);axi_write(12'h024,32'h00060008);
        axi_write(12'h004,3);read_expect(12'h008,1);
        send_frame();axi_write(12'h004,4);
        check_equal({31'd0,roi_enable},1,"ROI enable");
        check_equal({20'd0,roi_x0},0,"initial ROI x0");check_equal({20'd0,roi_x1},7,"initial ROI x1");
        read_expect(12'h040,1);read_expect(12'h048,1);
        read_expect(12'h050,32'h00060008);read_expect(12'h054,48);
        read_expect(12'h058,6144);read_expect(12'h064,24);read_expect(12'h068,5120);
        // Snapshot remains frozen while live results change.
        send_frame(1);read_expect(12'h040,1);read_expect(12'h058,6144);
        axi_write(12'h004,4);read_expect(12'h040,2);read_expect(12'h058,12240);read_expect(12'h060,48);
        // Shadow writes alone do not alter the active frame configuration.
        axi_write(12'h020,32'h00010002);axi_write(12'h024,32'h00040004);axi_write(12'h030,32'h00010014);
        send_frame();axi_write(12'h004,4);read_expect(12'h048,1);read_expect(12'h054,48);
        // Mid-frame APPLY must not relabel the old frame as using the new ROI.
        fork
            send_frame();
            begin repeat(14) @(negedge aclk);axi_write(12'h004,3);end
        join
        axi_write(12'h004,4);read_expect(12'h040,4);read_expect(12'h048,1);read_expect(12'h054,48);
        send_frame();axi_write(12'h004,4);
        read_expect(12'h040,5);read_expect(12'h048,2);read_expect(12'h04c,32'h00010002);
        check_equal({20'd0,roi_x0},2,"applied ROI x0");check_equal({20'd0,roi_x1},5,"applied ROI x1");
        check_equal({20'd0,roi_y0},1,"applied ROI y0");check_equal({20'd0,roi_y1},4,"applied ROI y1");
        read_expect(12'h050,32'h00040004);read_expect(12'h054,16);read_expect(12'h058,2048);
        read_expect(12'h064,4);read_expect(12'h068,2560);read_expect(12'h06c,1);
        read_expect(12'h070,5);read_expect(12'h074,2);read_expect(12'h044,32'h000101df);
        // Export actual RTL registers for Python-driver conformance tests.
        dump=$fopen("axi_snapshot.txt","w");
        for(integer address=0;address<=12'h074;address=address+4) begin
            axi_read(address[11:0],value);$fdisplay(dump,"%03h %08h",address,value);
        end
        $fclose(dump);
        send_frame(1);axi_write(12'h004,4);
        read_expect(12'h040,6);read_expect(12'h070,5);read_expect(12'h074,2);read_expect(12'h06c,1);
        axi_write(12'h004,2);axi_write(12'h004,4);
        read_expect(12'h040,6);read_expect(12'h06c,0);read_expect(12'h070,0);
        send_frame();axi_write(12'h004,4);read_expect(12'h070,7);read_expect(12'h074,2);
        axi_write(12'h004,1);send_frame();axi_write(12'h004,4);
        read_expect(12'h048,3);read_expect(12'h044,32'h000101df);
        // A disabled result is present but invalid, not a missing result.
        axi_write(12'h034,0);axi_write(12'h004,1);send_frame();axi_write(12'h004,4);
        read_expect(12'h040,9);read_expect(12'h044,32'h00010000);read_expect(12'h048,4);
        // Snapshot and publication on the same clock take the previous complete record.
        fork
            send_frame();
            begin wait(dut.impl.core.decide_publish===1'b1);axi_write(12'h004,4);end
        join
        read_expect(12'h040,9);read_expect(12'h048,4);read_expect(12'h054,16);
        axi_write(12'h004,4);read_expect(12'h040,10);
        // Reset abandons an incomplete AW and an outstanding read response.
        @(negedge aclk);s_axi_awaddr=12'h020;s_axi_awvalid=1;s_axi_araddr=0;s_axi_arvalid=1;
        @(negedge aclk);s_axi_awvalid=0;s_axi_arvalid=0;
        repeat(3) @(negedge aclk);
        check_equal({31'd0,dut.impl.aw_held},1,"pending AW before reset");
        check_equal({31'd0,s_axi_rvalid},1,"pending read before reset");
        aresetn=0;repeat(4) @(negedge aclk);aresetn=1;
        read_expect(12'h008,0);read_expect(12'h014,0);read_expect(12'h040,0);
        $display("PASS: AXI-Lite integration (%0d assertions)",checks);$finish;
    end
    initial begin #1000000;$fatal(1,"AXI integration timeout");end
endmodule
