`timescale 1ns/1ps
// Nonblocking AXIS statistics sink. All controls/results use aclk.
module axis_quality_gate #(
    parameter integer FRAME_WIDTH = 1280,
    parameter integer FRAME_HEIGHT = 720
) (
    input logic aclk, aresetn,
    input logic [23:0] s_axis_tdata,
    input logic [2:0] s_axis_tkeep, s_axis_tstrb,
    input logic s_axis_tuser, s_axis_tlast, s_axis_tvalid,
    output wire s_axis_tready,
    input logic cfg_enable,
    input logic [11:0] cfg_x0, cfg_y0, cfg_width, cfg_height,
    input logic [7:0] cfg_mean_min, cfg_mean_max, cfg_dark_level, cfg_bright_level,
    input logic [13:0] cfg_dark_max_bp, cfg_bright_max_bp,
    input logic [10:0] cfg_sharp_min,
    input logic [7:0] cfg_stable_n,
    input logic [31:0] cfg_token,
    input logic rearm,
    output logic result_update, result_valid,
    output logic [31:0] result_frame_id,
    output logic [31:0] result_config_id,
    output logic [11:0] result_x0, result_y0, result_width, result_height,
    output wire active_enable,
    output wire [11:0] active_x0, active_y0, active_width, active_height,
    output logic exposure_ok, sharpness_ok, quality_ok, stable_ok,
    output logic [1:0] frame_state,
    output logic [7:0] stable_count,
    output logic capture_pending,
    output logic [31:0] capture_frame_id, capture_config_id,
    output logic [31:0] pixel_count, luma_sum, dark_count, bright_count,
    output logic [31:0] gradient_count, gradient_sum
);
    assign s_axis_tready = 1'b1;
    typedef struct packed {
        logic enable;
        logic [11:0] x0, y0, width, height;
        logic [7:0] mean_min, mean_max, dark_level, bright_level;
        logic [13:0] dark_max_bp, bright_max_bp;
        logic [10:0] sharp_min;
        logic [7:0] stable_n;
        logic [31:0] token;
    } config_t;
    config_t incoming, active, completed;
    assign active_enable = active.enable;
    assign active_x0 = active.x0;
    assign active_y0 = active.y0;
    assign active_width = active.width;
    assign active_height = active.height;
    always_comb begin
        incoming.enable = cfg_enable;
        incoming.x0 = cfg_x0; incoming.y0 = cfg_y0;
        incoming.width = cfg_width; incoming.height = cfg_height;
        incoming.mean_min = cfg_mean_min; incoming.mean_max = cfg_mean_max;
        incoming.dark_level = cfg_dark_level; incoming.bright_level = cfg_bright_level;
        incoming.dark_max_bp = cfg_dark_max_bp; incoming.bright_max_bp = cfg_bright_max_bp;
        incoming.sharp_min = cfg_sharp_min; incoming.stable_n = cfg_stable_n;
        incoming.token = cfg_token;
    end
    function automatic logic valid_config(input config_t c);
        valid_config = c.enable && c.width >= 3 && c.height >= 3 &&
            ({1'b0,c.x0} + {1'b0,c.width} <= FRAME_WIDTH) &&
            ({1'b0,c.y0} + {1'b0,c.height} <= FRAME_HEIGHT) &&
            c.mean_min <= c.mean_max && c.dark_level < c.bright_level &&
            c.dark_max_bp <= 10000 && c.bright_max_bp <= 10000;
    endfunction

    logic [11:0] next_x, next_y, p_x, p_y;
    logic receiving;
    logic [31:0] sequence_id, p_id;
    logic p_valid, p_sof, p_eof, p_bad, p_restart;
    logic p_inside, p_gradient_inside, p_row_start;
    logic [7:0] p_luma;
    // Register channel products before their sum. The complete input-to-luma path
    // must also meet timing when driven by the baseline AXIS register slice.
    (* use_dsp = "yes" *) logic [15:0] front_r, front_g, front_b;
    logic front_valid, front_sof, front_last;
    logic [2:0] front_keep, front_strb;
    config_t front_config;
    always_ff @(posedge aclk) begin
        if (!aresetn) begin
            front_valid <= 0; front_sof <= 0; front_last <= 0;
            front_keep <= 0; front_strb <= 0;
            front_r <= 0; front_g <= 0; front_b <= 0; front_config <= '0;
        end else begin
            front_valid <= s_axis_tvalid;
            front_sof <= s_axis_tuser; front_last <= s_axis_tlast;
            front_keep <= s_axis_tkeep; front_strb <= s_axis_tstrb;
            front_r <= 16'd77 * s_axis_tdata[7:0];
            front_g <= 16'd150 * s_axis_tdata[15:8];
            front_b <= 16'd29 * s_axis_tdata[23:16];
            // Bind APPLY/token/ROI to the actual input SOF, not to a later cycle.
            if (s_axis_tvalid && s_axis_tuser) front_config <= incoming;
        end
    end
    wire [11:0] current_x = front_sof ? 12'd0 : next_x;
    wire [11:0] current_y = front_sof ? 12'd0 : next_y;
    wire accepted = front_valid && (receiving || front_sof);
    wire last_pixel = current_x == FRAME_WIDTH-1 && current_y == FRAME_HEIGHT-1;
    config_t current_config;
    always_comb current_config = front_sof ? front_config : active;
    wire [15:0] weighted_luma = front_r + front_g + front_b + 16'd128;
    always_ff @(posedge aclk) begin
        if (!aresetn) begin
            next_x <= 0; next_y <= 0; receiving <= 0; sequence_id <= 0;
            p_valid <= 0; p_sof <= 0; p_eof <= 0; p_bad <= 0; p_restart <= 0;
            p_x <= 0; p_y <= 0; p_luma <= 0; p_id <= 0; active <= '0;
            p_inside <= 0; p_gradient_inside <= 0; p_row_start <= 0;
        end else begin
            p_valid <= accepted;
            p_sof <= accepted && front_sof;
            p_eof <= accepted && last_pixel;
            if (accepted) begin
                p_x <= current_x; p_y <= current_y; p_luma <= weighted_luma[15:8];
                p_inside <= current_x >= current_config.x0 && current_y >= current_config.y0 &&
                    {1'b0,current_x} < ({1'b0,current_config.x0}+{1'b0,current_config.width}) &&
                    {1'b0,current_y} < ({1'b0,current_config.y0}+{1'b0,current_config.height});
                p_gradient_inside <= {1'b0,current_x} >= {1'b0,current_config.x0}+13'd2 &&
                    {1'b0,current_y} >= {1'b0,current_config.y0}+13'd2;
                p_row_start <= current_x == current_config.x0;
                p_bad <= (front_last != (current_x == FRAME_WIDTH-1)) ||
                    front_keep != 3'b111 || front_strb != 3'b111;
                p_restart <= front_sof && (receiving || front_config != active);
                p_id <= front_sof ? sequence_id + 1 : sequence_id;
                if (front_sof) begin
                    active <= front_config;
                    sequence_id <= sequence_id + 1;
                    receiving <= 1;
                end
                if (last_pixel) receiving <= 0;
                if (current_x == FRAME_WIDTH-1) begin
                    next_x <= 0; next_y <= current_y + 1;
                end else begin
                    next_x <= current_x + 1; next_y <= current_y;
                end
            end
        end
    end

    wire in_roi = p_inside;
    // Asynchronous read distributed line RAM: no reset, two prior ROI rows.
    (* ram_style = "distributed" *) logic [7:0] line1 [0:FRAME_WIDTH-1];
    (* ram_style = "distributed" *) logic [7:0] line2 [0:FRAME_WIDTH-1];
    logic [7:0] ta, tb, ma, mb, ba, bb;
    wire [7:0] tc = line2[p_x];
    wire [7:0] mc = line1[p_x];
    logic signed [11:0] gx, gy;
    logic g_valid, g_sof, g_eof;
    logic h_valid, h_sof, h_eof;
    logic [9:0] sobel_left, sobel_right, sobel_top, sobel_bottom;
    wire [11:0] abs_gx = gx[11] ? -gx : gx;
    wire [11:0] abs_gy = gy[11] ? -gy : gy;
    wire [12:0] magnitude = {1'b0,abs_gx} + {1'b0,abs_gy};

    logic [19:0] pc_acc, dc_acc, bc_acc, gc_acc;
    logic [31:0] ls_acc, gs_acc;
    logic bad_acc, restart_acc;
    wire [19:0] pc_next = (p_sof ? 20'd0 : pc_acc) + (in_roi ? 20'd1 : 20'd0);
    wire [31:0] ls_next = (p_sof ? 32'd0 : ls_acc) + (in_roi ? {24'd0,p_luma} : 32'd0);
    wire [19:0] dc_next = (p_sof ? 20'd0 : dc_acc) +
        ((in_roi && p_luma < active.dark_level) ? 20'd1 : 20'd0);
    wire [19:0] bc_next = (p_sof ? 20'd0 : bc_acc) +
        ((in_roi && p_luma > active.bright_level) ? 20'd1 : 20'd0);
    wire bad_next = (p_sof ? 1'b0 : bad_acc) || p_bad;
    wire [19:0] gc_next = (h_sof ? 20'd0 : gc_acc) + (h_valid ? 20'd1 : 20'd0);
    wire [31:0] gs_next = (h_sof ? 32'd0 : gs_acc) + (h_valid ? {19'd0,magnitude} : 32'd0);

    logic [19:0] done_pc, done_dc, done_bc;
    logic [31:0] done_ls, done_id;
    logic done_bad, done_restart;
    // Geometry is constant during a frame. Pipeline the products well before EOF.
    logic [11:0] width_minus2, height_minus2;
    logic [23:0] expected_pixels, expected_gradients;
    logic geometry_valid;
    logic [23:0] done_expected_pixels, done_expected_gradients;
    logic done_geometry_valid;
    always_ff @(posedge aclk) begin
        if (!aresetn) begin
            width_minus2 <= 0; height_minus2 <= 0;
            expected_pixels <= 0; expected_gradients <= 0; geometry_valid <= 0;
        end else begin
            width_minus2 <= active.width - 12'd2;
            height_minus2 <= active.height - 12'd2;
            expected_pixels <= active.width * active.height;
            expected_gradients <= width_minus2 * height_minus2;
            geometry_valid <= valid_config(active);
        end
    end
    always_ff @(posedge aclk) begin
        if (!aresetn) begin
            pc_acc <= 0; dc_acc <= 0; bc_acc <= 0; ls_acc <= 0;
            bad_acc <= 0; restart_acc <= 0;
            ta <= 0; tb <= 0; ma <= 0; mb <= 0; ba <= 0; bb <= 0;
            sobel_left <= 0; sobel_right <= 0; sobel_top <= 0; sobel_bottom <= 0;
            g_valid <= 0; g_sof <= 0; g_eof <= 0;
            completed <= '0; done_pc <= 0; done_dc <= 0; done_bc <= 0;
            done_ls <= 0; done_id <= 0; done_bad <= 0; done_restart <= 0;
            done_expected_pixels <= 0; done_expected_gradients <= 0; done_geometry_valid <= 0;
        end else begin
            g_valid <= 0;
            g_sof <= p_valid && p_sof;
            g_eof <= p_valid && p_eof;
            if (p_valid) begin
                pc_acc <= pc_next; ls_acc <= ls_next; dc_acc <= dc_next; bc_acc <= bc_next;
                bad_acc <= bad_next;
                if (p_sof) restart_acc <= p_restart;
                if (in_roi) begin
                    line2[p_x] <= mc; line1[p_x] <= p_luma;
                    if (p_row_start) begin
                        ta <= 0; tb <= tc; ma <= 0; mb <= mc; ba <= 0; bb <= p_luma;
                    end else begin
                        ta <= tb; tb <= tc; ma <= mb; mb <= mc; ba <= bb; bb <= p_luma;
                    end
                    if (p_gradient_inside) begin
                        g_valid <= 1;
                        sobel_right <= {2'b0,tc} + {1'b0,mc,1'b0} + {2'b0,p_luma};
                        sobel_left <= {2'b0,ta} + {1'b0,ma,1'b0} + {2'b0,ba};
                        sobel_bottom <= {2'b0,ba} + {1'b0,bb,1'b0} + {2'b0,p_luma};
                        sobel_top <= {2'b0,ta} + {1'b0,tb,1'b0} + {2'b0,tc};
                    end
                end
                if (p_eof) begin
                    completed <= active; done_pc <= pc_next; done_ls <= ls_next;
                    done_dc <= dc_next; done_bc <= bc_next; done_bad <= bad_next;
                    done_id <= p_id; done_restart <= restart_acc;
                    done_expected_pixels <= expected_pixels;
                    done_expected_gradients <= expected_gradients;
                    done_geometry_valid <= geometry_valid;
                end
            end
        end
    end

    always_ff @(posedge aclk) begin
        if (!aresetn) begin
            h_valid <= 0; h_sof <= 0; h_eof <= 0; gx <= 0; gy <= 0;
        end else begin
            h_valid <= g_valid; h_sof <= g_sof; h_eof <= g_eof;
            gx <= $signed({2'b0,sobel_right}) - $signed({2'b0,sobel_left});
            gy <= $signed({2'b0,sobel_bottom}) - $signed({2'b0,sobel_top});
        end
    end

    logic prepare_products, publish;
    logic [47:0] mean_lo_product, mean_hi_product, dark_product, dark_limit_product;
    logic [47:0] bright_product, bright_limit_product, sharp_limit_product;
    logic [31:0] done_gs;
    logic [19:0] done_gc;
    logic complete_valid;
    always_ff @(posedge aclk) begin
        if (!aresetn) begin
            gc_acc <= 0; gs_acc <= 0; prepare_products <= 0; publish <= 0; done_gs <= 0; done_gc <= 0;
            mean_lo_product <= 0; mean_hi_product <= 0;
            dark_product <= 0; dark_limit_product <= 0;
            bright_product <= 0; bright_limit_product <= 0; sharp_limit_product <= 0;
            complete_valid <= 0;
        end else begin
            prepare_products <= h_eof;
            publish <= prepare_products;
            gc_acc <= gc_next; gs_acc <= gs_next;
            if (h_eof) begin
                done_gs <= gs_next; done_gc <= gc_next;
            end
            if (prepare_products) begin
                mean_lo_product <= completed.mean_min * done_pc;
                mean_hi_product <= completed.mean_max * done_pc;
                dark_product <= done_dc * 14'd10000;
                dark_limit_product <= completed.dark_max_bp * done_pc;
                bright_product <= done_bc * 14'd10000;
                bright_limit_product <= completed.bright_max_bp * done_pc;
                sharp_limit_product <= completed.sharp_min * done_gc;
                complete_valid <= done_geometry_valid && !done_bad &&
                    done_pc == done_expected_pixels && done_gc == done_expected_gradients;
            end
        end
    end
    wire calculated_exposure = done_ls >= mean_lo_product && done_ls <= mean_hi_product &&
        dark_product <= dark_limit_product && bright_product <= bright_limit_product;
    wire calculated_sharpness = done_gc != 0 && done_gs >= sharp_limit_product;
    logic decide_publish, verdict_valid, pass_exposure, pass_sharpness, pass_quality;
    always_ff @(posedge aclk) begin
        if (!aresetn) begin
            decide_publish <= 0; verdict_valid <= 0;
            pass_exposure <= 0; pass_sharpness <= 0; pass_quality <= 0;
        end else begin
            decide_publish <= publish;
            if (publish) begin
                verdict_valid <= complete_valid;
                pass_exposure <= complete_valid && calculated_exposure;
                pass_sharpness <= complete_valid && calculated_sharpness;
                pass_quality <= complete_valid && calculated_exposure && calculated_sharpness;
            end
        end
    end
    wire [7:0] streak_base = done_restart ? 8'd0 : stable_count;
    wire [7:0] streak_next = pass_quality ?
        (streak_base == 255 ? 8'd255 : streak_base+8'd1) : 8'd0;
    wire [7:0] needed = completed.stable_n == 0 ? 8'd1 : completed.stable_n;
    logic armed;
    always_ff @(posedge aclk) begin
        if (!aresetn) begin
            result_update <= 0; result_valid <= 0; result_frame_id <= 0;
            result_config_id <= 0;
            result_x0 <= 0; result_y0 <= 0; result_width <= 0; result_height <= 0;
            exposure_ok <= 0; sharpness_ok <= 0; quality_ok <= 0; stable_ok <= 0;
            frame_state <= 0; stable_count <= 0; capture_pending <= 0; armed <= 0;
            capture_frame_id <= 0; capture_config_id <= 0;
            pixel_count <= 0; luma_sum <= 0; dark_count <= 0; bright_count <= 0;
            gradient_count <= 0; gradient_sum <= 0;
        end else begin
            result_update <= 0;
            if (decide_publish) begin
                result_update <= 1; result_frame_id <= done_id;
                result_config_id <= completed.token;
                result_x0 <= completed.x0; result_y0 <= completed.y0;
                result_width <= completed.width; result_height <= completed.height;
                result_valid <= verdict_valid;
                exposure_ok <= pass_exposure;
                sharpness_ok <= pass_sharpness;
                quality_ok <= pass_quality;
                stable_count <= streak_next;
                stable_ok <= pass_quality && streak_next >= needed;
                frame_state <= !verdict_valid ? 2'b00 : !pass_quality ? 2'b01 :
                    streak_next < needed ? 2'b10 : 2'b11;
                pixel_count <= {12'd0,done_pc}; luma_sum <= done_ls;
                dark_count <= {12'd0,done_dc}; bright_count <= {12'd0,done_bc};
                gradient_count <= {12'd0,done_gc}; gradient_sum <= done_gs;
                if (armed && pass_quality && streak_next >= needed) begin
                    capture_pending <= 1; armed <= 0;
                    capture_frame_id <= done_id; capture_config_id <= completed.token;
                end
            end
            if (rearm) begin
                capture_pending <= 0; armed <= 1;
                capture_frame_id <= 0; capture_config_id <= 0;
                stable_count <= 0; stable_ok <= 0; frame_state <= 0;
            end
        end
    end
endmodule
