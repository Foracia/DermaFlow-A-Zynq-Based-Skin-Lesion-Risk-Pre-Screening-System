`timescale 1ns/1ps
// One-clock AXI-Lite wrapper. Use a real AXI clock converter if PS control is on another clock.
module axis_quality_gate_axi #(
    parameter integer FRAME_WIDTH=1280,
    parameter integer FRAME_HEIGHT=720
) (
    (* X_INTERFACE_INFO="xilinx.com:signal:clock:1.0 aclk CLK", X_INTERFACE_PARAMETER="XIL_INTERFACENAME aclk, ASSOCIATED_BUSIF S_AXI:S_AXIS, ASSOCIATED_RESET aresetn" *)
    input wire aclk,
    (* X_INTERFACE_INFO="xilinx.com:signal:reset:1.0 aresetn RST", X_INTERFACE_PARAMETER="POLARITY ACTIVE_LOW" *)
    input wire aresetn,
    (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 S_AXIS TDATA", X_INTERFACE_PARAMETER="TDATA_NUM_BYTES 3, TUSER_WIDTH 1, HAS_TLAST 1, HAS_TKEEP 1, HAS_TSTRB 1, HAS_TREADY 1" *)
    input wire [23:0] s_axis_tdata,
    (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 S_AXIS TKEEP" *) input wire [2:0] s_axis_tkeep,
    (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 S_AXIS TSTRB" *) input wire [2:0] s_axis_tstrb,
    (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 S_AXIS TUSER" *) input wire s_axis_tuser,
    (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 S_AXIS TLAST" *) input wire s_axis_tlast,
    (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 S_AXIS TVALID" *) input wire s_axis_tvalid,
    (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 S_AXIS TREADY" *) output wire s_axis_tready,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI AWADDR", X_INTERFACE_PARAMETER="PROTOCOL AXI4LITE, DATA_WIDTH 32, ADDR_WIDTH 12, NUM_READ_OUTSTANDING 1, NUM_WRITE_OUTSTANDING 1" *)
    input wire [11:0] s_axi_awaddr,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI AWPROT" *) input wire [2:0] s_axi_awprot,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI AWVALID" *) input wire s_axi_awvalid,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI AWREADY" *) output wire s_axi_awready,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI WDATA" *) input wire [31:0] s_axi_wdata,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI WSTRB" *) input wire [3:0] s_axi_wstrb,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI WVALID" *) input wire s_axi_wvalid,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI WREADY" *) output wire s_axi_wready,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI BRESP" *) output logic [1:0] s_axi_bresp,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI BVALID" *) output logic s_axi_bvalid,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI BREADY" *) input wire s_axi_bready,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI ARADDR" *) input wire [11:0] s_axi_araddr,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI ARPROT" *) input wire [2:0] s_axi_arprot,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI ARVALID" *) input wire s_axi_arvalid,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI ARREADY" *) output wire s_axi_arready,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI RDATA" *) output logic [31:0] s_axi_rdata,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI RRESP" *) output logic [1:0] s_axi_rresp,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI RVALID" *) output logic s_axi_rvalid,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI RREADY" *) input wire s_axi_rready,
    output wire [1:0] frame_state,
    output wire capture_pending,
    output wire roi_enable,
    output wire [11:0] roi_x0,roi_y0,roi_x1,roi_y1
);
    localparam [31:0] ABI_ID=32'h51475402;
    logic [31:0] shadow [0:5];
    logic [31:0] committed [0:5];
    logic [31:0] commit_id, snapshot_seq;
    logic rearm;
    wire result_update, result_valid, exposure_ok, sharpness_ok, quality_ok, stable_ok;
    wire [31:0] result_frame_id, result_config_id, capture_frame_id, capture_config_id;
    wire [11:0] result_x0,result_y0,result_width,result_height;
    wire active_enable;
    wire [11:0] active_width,active_height;
    wire [12:0] roi_end_x={1'b0,roi_x0}+{1'b0,active_width};
    wire [12:0] roi_end_y={1'b0,roi_y0}+{1'b0,active_height};
    assign roi_x1=roi_end_x-13'd1;
    assign roi_y1=roi_end_y-13'd1;
    assign roi_enable=active_enable && active_width>=3 && active_height>=3 &&
        roi_end_x<=FRAME_WIDTH && roi_end_y<=FRAME_HEIGHT;
    wire [7:0] stable_count;
    wire [31:0] pixel_count,luma_sum,dark_count,bright_count,gradient_count,gradient_sum;
    axis_quality_gate #(.FRAME_WIDTH(FRAME_WIDTH),.FRAME_HEIGHT(FRAME_HEIGHT)) core (
        .aclk(aclk),.aresetn(aresetn),
        .s_axis_tdata(s_axis_tdata),.s_axis_tkeep(s_axis_tkeep),.s_axis_tstrb(s_axis_tstrb),
        .s_axis_tuser(s_axis_tuser),.s_axis_tlast(s_axis_tlast),.s_axis_tvalid(s_axis_tvalid),.s_axis_tready(s_axis_tready),
        .cfg_enable(committed[5][0]),
        .cfg_x0(committed[0][11:0]),.cfg_y0(committed[0][27:16]),
        .cfg_width(committed[1][11:0]),.cfg_height(committed[1][27:16]),
        .cfg_mean_min(committed[2][7:0]),.cfg_mean_max(committed[2][15:8]),
        .cfg_dark_level(committed[2][23:16]),.cfg_bright_level(committed[2][31:24]),
        .cfg_dark_max_bp(committed[3][13:0]),.cfg_bright_max_bp(committed[3][29:16]),
        .cfg_sharp_min(committed[4][10:0]),.cfg_stable_n(committed[4][23:16]),.cfg_token(commit_id),
        .rearm(rearm),.result_update(result_update),.result_valid(result_valid),
        .result_frame_id(result_frame_id),.result_config_id(result_config_id),
        .result_x0(result_x0),.result_y0(result_y0),.result_width(result_width),.result_height(result_height),
        .active_enable(active_enable),.active_x0(roi_x0),.active_y0(roi_y0),
        .active_width(active_width),.active_height(active_height),
        .exposure_ok(exposure_ok),.sharpness_ok(sharpness_ok),.quality_ok(quality_ok),.stable_ok(stable_ok),
        .frame_state(frame_state),.stable_count(stable_count),.capture_pending(capture_pending),
        .capture_frame_id(capture_frame_id),.capture_config_id(capture_config_id),
        .pixel_count(pixel_count),.luma_sum(luma_sum),.dark_count(dark_count),.bright_count(bright_count),
        .gradient_count(gradient_count),.gradient_sum(gradient_sum)
    );

    logic [31:0] latest [0:10];
    logic [31:0] snapshot [0:13];
    wire [31:0] result_flags = {15'd0,1'b1,stable_count,frame_state,1'b0,
        stable_ok,quality_ok,sharpness_ok,exposure_ok,result_valid};
    wire [31:0] live_flags = {15'd0,latest[1][16],stable_count,frame_state,capture_pending,
        stable_ok,quality_ok,sharpness_ok,exposure_ok,result_valid};
    logic aw_held,w_held;
    logic [11:0] aw_address;
    logic [31:0] write_data;
    logic [3:0] write_strobes;
    assign s_axi_awready = !aw_held && !s_axi_bvalid;
    assign s_axi_wready = !w_held && !s_axi_bvalid;
    assign s_axi_arready = !s_axi_rvalid;
    function automatic [31:0] merge_bytes(input [31:0] old_value,new_value,input [3:0] strobes);
        for(integer b=0;b<4;b=b+1)
            merge_bytes[b*8+:8] = strobes[b] ? new_value[b*8+:8] : old_value[b*8+:8];
    endfunction
    wire [31:0] command = merge_bytes(32'd0,write_data,write_strobes);
    logic [31:0] read_value;
    logic read_mapped;
    always_comb begin
        read_value=0; read_mapped=1;
        case(s_axi_araddr)
            12'h000: read_value=ABI_ID;
            12'h004: read_value=0;
            12'h008: read_value=commit_id;
            12'h00c: read_value=live_flags;
            12'h010: read_value=result_frame_id;
            12'h014: read_value=snapshot_seq;
            12'h018: read_value=result_config_id;
            12'h01c: read_value=(FRAME_HEIGHT << 16) | FRAME_WIDTH;
            12'h020: read_value=shadow[0];
            12'h024: read_value=shadow[1];
            12'h028: read_value=shadow[2];
            12'h02c: read_value=shadow[3];
            12'h030: read_value=shadow[4];
            12'h034: read_value=shadow[5];
            12'h038: read_value=capture_frame_id;
            12'h03c: read_value=capture_config_id;
            12'h040: read_value=snapshot[0];
            12'h044: read_value=snapshot[1];
            12'h048: read_value=snapshot[2];
            12'h04c: read_value=snapshot[3];
            12'h050: read_value=snapshot[4];
            12'h054: read_value=snapshot[5];
            12'h058: read_value=snapshot[6];
            12'h05c: read_value=snapshot[7];
            12'h060: read_value=snapshot[8];
            12'h064: read_value=snapshot[9];
            12'h068: read_value=snapshot[10];
            12'h06c: read_value=snapshot[11];
            12'h070: read_value=snapshot[12];
            12'h074: read_value=snapshot[13];
            default: read_mapped=0;
        endcase
    end
    integer i;
    always_ff @(posedge aclk) begin
        if(!aresetn) begin
            aw_held<=0;w_held<=0;aw_address<=0;write_data<=0;write_strobes<=0;
            s_axi_bvalid<=0;s_axi_bresp<=0;s_axi_rvalid<=0;s_axi_rresp<=0;s_axi_rdata<=0;
            commit_id<=0;snapshot_seq<=0;rearm<=0;
            shadow[0]<=(180<<16)|320;shadow[1]<=(360<<16)|640;
            shadow[2]<=(239<<24)|(16<<16)|(210<<8)|40;
            shadow[3]<=(200<<16)|200;shadow[4]<=(3<<16)|20;shadow[5]<=1;
            for(i=0;i<6;i=i+1) committed[i]<=0;
            for(i=0;i<11;i=i+1) latest[i]<=0;
            for(i=0;i<14;i=i+1) snapshot[i]<=0;
        end else begin
            rearm<=0;
            if(result_update) begin
                latest[0]<=result_frame_id; latest[1]<=result_flags; latest[2]<=result_config_id;
                latest[3]<={4'd0,result_y0,4'd0,result_x0};
                latest[4]<={4'd0,result_height,4'd0,result_width};
                latest[5]<=pixel_count;latest[6]<=luma_sum;latest[7]<=dark_count;
                latest[8]<=bright_count;latest[9]<=gradient_count;latest[10]<=gradient_sum;
            end
            if(s_axi_awready && s_axi_awvalid) begin aw_held<=1;aw_address<=s_axi_awaddr;end
            if(s_axi_wready && s_axi_wvalid) begin w_held<=1;write_data<=s_axi_wdata;write_strobes<=s_axi_wstrb;end
            if(s_axi_bvalid && s_axi_bready) s_axi_bvalid<=0;
            if(aw_held && w_held && !s_axi_bvalid) begin
                aw_held<=0;w_held<=0;s_axi_bvalid<=1;s_axi_bresp<=2'b00;
                case(aw_address)
                    12'h004: begin
                        if((command & 32'hfffffff8)!=0) s_axi_bresp<=2'b10;
                        else begin
                            if(command[0]) begin
                                for(i=0;i<6;i=i+1) committed[i]<=shadow[i];
                                commit_id<=commit_id+1;
                            end
                            if(command[1]) rearm<=1;
                            if(command[2]) begin
                                for(i=0;i<11;i=i+1) snapshot[i]<=latest[i];
                                snapshot[11]<={31'd0,capture_pending};
                                snapshot[12]<=capture_frame_id;snapshot[13]<=capture_config_id;
                                snapshot_seq<=snapshot_seq+1;
                            end
                        end
                    end
                    12'h020:shadow[0]<=merge_bytes(shadow[0],write_data,write_strobes);
                    12'h024:shadow[1]<=merge_bytes(shadow[1],write_data,write_strobes);
                    12'h028:shadow[2]<=merge_bytes(shadow[2],write_data,write_strobes);
                    12'h02c:shadow[3]<=merge_bytes(shadow[3],write_data,write_strobes);
                    12'h030:shadow[4]<=merge_bytes(shadow[4],write_data,write_strobes);
                    12'h034:shadow[5]<=merge_bytes(shadow[5],write_data,write_strobes);
                    default:s_axi_bresp<=2'b10;
                endcase
            end
            if(s_axi_rvalid && s_axi_rready) s_axi_rvalid<=0;
            if(s_axi_arready && s_axi_arvalid) begin
                s_axi_rvalid<=1;s_axi_rdata<=read_value;s_axi_rresp<=read_mapped ? 2'b00 : 2'b10;
            end
        end
    end
endmodule
