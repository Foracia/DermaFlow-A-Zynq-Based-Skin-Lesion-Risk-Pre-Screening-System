`timescale 1ns / 1ps
// Baseline overlay with a two-cycle control preparation pipeline.
// AXIS pixels/sidebands remain combinational passthrough; controls latch per frame.

module axis_frame_overlay (
    input  wire        aclk,
    input  wire        aresetn,

    input  wire [23:0] s_axis_tdata,
    input  wire [2:0]  s_axis_tkeep,
    input  wire [2:0]  s_axis_tstrb,
    input  wire        s_axis_tuser,
    input  wire        s_axis_tlast,
    input  wire        s_axis_tvalid,
    output wire        s_axis_tready,

    output wire [23:0] m_axis_tdata,
    output wire [2:0]  m_axis_tkeep,
    output wire [2:0]  m_axis_tstrb,
    output wire        m_axis_tuser,
    output wire        m_axis_tlast,
    output wire        m_axis_tvalid,
    input  wire        m_axis_tready,

    input  wire        overlay_enable,
    input  wire [1:0]  frame_state,
    input  wire [11:0] frame_x0,
    input  wire [11:0] frame_y0,
    input  wire [11:0] frame_x1,
    input  wire [11:0] frame_y1,
    input  wire [3:0]  line_width
);

    reg [11:0] pixel_x;
    reg [11:0] pixel_y;

    // Sample the complete control bundle, then prepare border thresholds.
    // This separates ROI endpoint arithmetic from pixel comparisons.
    reg sampled_enable, prepared_enable;
    reg [1:0] sampled_state, prepared_state;
    reg [11:0] sampled_x0, sampled_y0, sampled_x1, sampled_y1;
    reg [11:0] prepared_x0, prepared_y0, prepared_x1, prepared_y1;
    reg [3:0] sampled_width;
    reg [12:0] prepared_left_end, prepared_right_start;
    reg [12:0] prepared_top_end, prepared_bottom_start;
    wire [12:0] sampled_x1_plus1 = {1'b0,sampled_x1} + 13'd1;
    wire [12:0] sampled_y1_plus1 = {1'b0,sampled_y1} + 13'd1;
    wire [12:0] border_width = {9'd0,sampled_width};
    always @(posedge aclk) begin
        if (!aresetn) begin
            sampled_enable <= 0; sampled_state <= 0;
            sampled_x0 <= 0; sampled_y0 <= 0; sampled_x1 <= 0; sampled_y1 <= 0; sampled_width <= 1;
            prepared_enable <= 0; prepared_state <= 0;
            prepared_x0 <= 0; prepared_y0 <= 0; prepared_x1 <= 0; prepared_y1 <= 0;
            prepared_left_end <= 0; prepared_right_start <= 0;
            prepared_top_end <= 0; prepared_bottom_start <= 0;
        end else begin
            sampled_enable <= overlay_enable; sampled_state <= frame_state;
            sampled_x0 <= frame_x0; sampled_y0 <= frame_y0;
            sampled_x1 <= frame_x1; sampled_y1 <= frame_y1;
            sampled_width <= line_width == 0 ? 4'd1 : line_width;
            // At a stalled SOF these controls directly drive output TDATA.
            // Freeze the complete prepared bundle until that pixel transfers.
            if (!(s_axis_tvalid && s_axis_tuser && !m_axis_tready)) begin
            prepared_enable <= sampled_enable; prepared_state <= sampled_state;
            prepared_x0 <= sampled_x0; prepared_y0 <= sampled_y0;
            prepared_x1 <= sampled_x1; prepared_y1 <= sampled_y1;
            prepared_left_end <= {1'b0,sampled_x0} + border_width;
            prepared_top_end <= {1'b0,sampled_y0} + border_width;
            prepared_right_start <= sampled_x1_plus1 >= border_width ? sampled_x1_plus1-border_width : 13'd0;
            prepared_bottom_start <= sampled_y1_plus1 >= border_width ? sampled_y1_plus1-border_width : 13'd0;
            end
        end
    end

    // Prepared controls latched at the start of each displayed frame.
    reg        active_overlay_enable;
    reg [1:0]  active_frame_state;
    reg [11:0] active_frame_x0;
    reg [11:0] active_frame_y0;
    reg [11:0] active_frame_x1;
    reg [11:0] active_frame_y1;
    reg [12:0] active_left_end, active_right_start, active_top_end, active_bottom_start;

    wire transfer;
    assign transfer = s_axis_tvalid && s_axis_tready;

    wire [11:0] current_x;
    wire [11:0] current_y;

    assign current_x = s_axis_tuser ? 12'd0 : pixel_x;
    assign current_y = s_axis_tuser ? 12'd0 : pixel_y;

    // Use prepared controls for the first pixel,
    // then use the latched values for the rest of the frame.
    wire        used_overlay_enable;
    wire [1:0]  used_frame_state;
    wire [11:0] used_frame_x0;
    wire [11:0] used_frame_y0;
    wire [11:0] used_frame_x1;
    wire [11:0] used_frame_y1;
    wire [12:0] used_left_end, used_right_start, used_top_end, used_bottom_start;

    assign used_overlay_enable =
        s_axis_tuser ? prepared_enable : active_overlay_enable;

    assign used_frame_state =
        s_axis_tuser ? prepared_state : active_frame_state;

    assign used_frame_x0 =
        s_axis_tuser ? prepared_x0 : active_frame_x0;

    assign used_frame_y0 =
        s_axis_tuser ? prepared_y0 : active_frame_y0;

    assign used_frame_x1 =
        s_axis_tuser ? prepared_x1 : active_frame_x1;

    assign used_frame_y1 =
        s_axis_tuser ? prepared_y1 : active_frame_y1;

    assign used_left_end = s_axis_tuser ? prepared_left_end : active_left_end;
    assign used_right_start = s_axis_tuser ? prepared_right_start : active_right_start;
    assign used_top_end = s_axis_tuser ? prepared_top_end : active_top_end;
    assign used_bottom_start = s_axis_tuser ? prepared_bottom_start : active_bottom_start;

    always @(posedge aclk) begin
        if (!aresetn) begin
            active_overlay_enable <= 1'b0;
            active_frame_state    <= 2'b00;
            active_frame_x0       <= 12'd0;
            active_frame_y0       <= 12'd0;
            active_frame_x1       <= 12'd0;
            active_frame_y1       <= 12'd0;
            active_left_end <= 0; active_right_start <= 0;
            active_top_end <= 0; active_bottom_start <= 0;
        end
        else if (transfer && s_axis_tuser) begin
            active_overlay_enable <= prepared_enable;
            active_frame_state    <= prepared_state;
            active_frame_x0       <= prepared_x0;
            active_frame_y0       <= prepared_y0;
            active_frame_x1       <= prepared_x1;
            active_frame_y1       <= prepared_y1;
            active_left_end <= prepared_left_end; active_right_start <= prepared_right_start;
            active_top_end <= prepared_top_end; active_bottom_start <= prepared_bottom_start;
        end
    end

    always @(posedge aclk) begin
        if (!aresetn) begin
            pixel_x <= 12'd0;
            pixel_y <= 12'd0;
        end
        else if (transfer) begin
            if (s_axis_tuser) begin
                if (s_axis_tlast) begin
                    pixel_x <= 12'd0;
                    pixel_y <= 12'd1;
                end
                else begin
                    pixel_x <= 12'd1;
                    pixel_y <= 12'd0;
                end
            end
            else if (s_axis_tlast) begin
                pixel_x <= 12'd0;
                pixel_y <= pixel_y + 12'd1;
            end
            else begin
                pixel_x <= pixel_x + 12'd1;
            end
        end
    end

    wire inside_x;
    wire inside_y;
    wire left_edge;
    wire right_edge;
    wire top_edge;
    wire bottom_edge;
    wire frame_pixel;

    assign inside_x =
        (current_x >= used_frame_x0) &&
        (current_x <= used_frame_x1);

    assign inside_y =
        (current_y >= used_frame_y0) &&
        (current_y <= used_frame_y1);

    assign left_edge = {1'b0,current_x} < used_left_end;
    assign right_edge = {1'b0,current_x} >= used_right_start;
    assign top_edge = {1'b0,current_y} < used_top_end;
    assign bottom_edge = {1'b0,current_y} >= used_bottom_start;

    assign frame_pixel =
        used_overlay_enable &&
        inside_x &&
        inside_y &&
        (left_edge || right_edge || top_edge || bottom_edge);

    // Output AXIS byte order:
// [23:16] = B, [15:8] = G, [7:0] = R
// 00 = white, 01 = red, 10 = yellow, 11 = green
    wire [23:0] frame_color;

    assign frame_color =
        (used_frame_state == 2'b01) ? 24'h0000FF :
        (used_frame_state == 2'b10) ? 24'h00FFFF :
        (used_frame_state == 2'b11) ? 24'h00FF00 :
                                      24'hFFFFFF;

    assign s_axis_tready = m_axis_tready;
    assign m_axis_tvalid = s_axis_tvalid;

    assign m_axis_tdata =
        frame_pixel ? frame_color : s_axis_tdata;

    assign m_axis_tkeep = s_axis_tkeep;
    assign m_axis_tstrb = s_axis_tstrb;
    assign m_axis_tuser = s_axis_tuser;
    assign m_axis_tlast = s_axis_tlast;

endmodule
