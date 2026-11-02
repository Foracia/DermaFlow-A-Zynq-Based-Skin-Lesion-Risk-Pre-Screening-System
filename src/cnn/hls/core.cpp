#include "core.h"
#include "stem16.h"
#include "weights.h"
#ifndef __SYNTHESIS__
#include "debug.h"
#endif
void grouped_network(hls::stream<ap_uint<24>>& x,hls::stream<ap_uint<16>>& y){
#pragma HLS INTERFACE axis port=x,y
#pragma HLS DATAFLOW
hls::stream<ap_uint<64>> c0("c0");
#pragma HLS STREAM variable=c0 depth=8
#pragma HLS BIND_STORAGE variable=c0 type=fifo impl=lutram
hls::stream<ap_uint<64>> p0("p0");
#pragma HLS STREAM variable=p0 depth=8
#pragma HLS BIND_STORAGE variable=p0 type=fifo impl=lutram
hls::stream<ap_uint<64>> c1("c1");
#pragma HLS STREAM variable=c1 depth=8
#pragma HLS BIND_STORAGE variable=c1 type=fifo impl=lutram
hls::stream<ap_uint<64>> p1("p1");
#pragma HLS STREAM variable=p1 depth=8
#pragma HLS BIND_STORAGE variable=p1 type=fifo impl=lutram
hls::stream<ap_uint<64>> c2("c2");
#pragma HLS STREAM variable=c2 depth=8
#pragma HLS BIND_STORAGE variable=c2 type=fifo impl=lutram
hls::stream<ap_uint<64>> p2("p2");
#pragma HLS STREAM variable=p2 depth=8
#pragma HLS BIND_STORAGE variable=p2 type=fifo impl=lutram
hls::stream<ap_uint<64>> c3("c3");
#pragma HLS STREAM variable=c3 depth=8
#pragma HLS BIND_STORAGE variable=c3 type=fifo impl=lutram
hls::stream<ap_uint<64>> avg("avg");
#pragma HLS STREAM variable=avg depth=8
#pragma HLS BIND_STORAGE variable=avg type=fifo impl=lutram
grouped::stem16(x,c0,weights_0,biases_0);
#ifndef __SYNTHESIS__
group_dump(c0,"Relu_0");
#endif
grouped::pool<64,64,64,3,2,1,8>(c0,p0);
#ifndef __SYNTHESIS__
group_dump(p0,"MaxPool_0");
#endif
grouped::conv<32,32,64,32,3,1,1,8,8,6,7>(p0,c1,weights_1,biases_1);
#ifndef __SYNTHESIS__
group_dump(c1,"Relu_1");
#endif
grouped::pool<32,32,32,2,2,0,8>(c1,p1);
#ifndef __SYNTHESIS__
group_dump(p1,"MaxPool_1");
#endif
grouped::conv<16,16,32,64,3,1,1,8,8,5,8>(p1,c2,weights_2,biases_2);
#ifndef __SYNTHESIS__
group_dump(c2,"Relu_2");
#endif
grouped::pool<16,16,64,2,2,0,8>(c2,p2);
#ifndef __SYNTHESIS__
group_dump(p2,"MaxPool_2");
#endif
grouped::conv<8,8,64,128,3,1,1,8,8,6,6>(p2,c3,weights_3,biases_3);
#ifndef __SYNTHESIS__
group_dump(c3,"Relu_3");
#endif
grouped::gap<8>(c3,avg);
#ifndef __SYNTHESIS__
group_dump(avg,"AveragePool_0");
#endif
grouped::head<8>(avg,y,weights_head,bias_head);
#ifndef __SYNTHESIS__
group_dump(y,"bn_Add_0");
#endif
}

#ifndef __SYNTHESIS__
void stem16_boundary(hls::stream<ap_uint<24>>& x,hls::stream<ap_uint<64>>& y){grouped::stem16(x,y,weights_0,biases_0);}
#endif
