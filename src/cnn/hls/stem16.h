#pragma once
#include "grouped.h"
namespace grouped {
// system exact same7x7/stride2/pad3 Conv:16 MAC lanes,8-channel output packets.
inline void stem16(hls::stream<ap_uint<24>>& input,hls::stream<ap_uint<64>>& output,
                   const ap_uint<128> weights[588],const ap_int<32> biases[64]) {
    const int PW=134,PH=134,K=7,PO=16,D=147;
    static ap_uint<24> rows[K][PW];
    #pragma HLS ARRAY_PARTITION variable=rows complete dim=1
    #pragma HLS BIND_STORAGE variable=rows type=ram_s2p impl=bram
    #pragma HLS BIND_STORAGE variable=weights type=rom_1p impl=bram
    #pragma HLS INLINE off
    ap_uint<4> slot=0;
StemRow:
    for(int y=0;y<PH;++y) {
    StemColumn:
        for(int x=0;x<PW;++x) {
            #pragma HLS PIPELINE off
            ap_uint<24> pack=0;
            if(y>=3 && y<131 && x>=3 && x<131)pack=input.read();
            rows[slot][x]=pack;
            if(y>=6 && x>=6 && (y-6)%2==0 && (x-6)%2==0) {
            StemOutputGroup:
                for(int og=0;og<4;++og) {
                    #pragma HLS PIPELINE off
                    ap_int<32> acc[16];
                    #pragma HLS ARRAY_PARTITION variable=acc complete
                StemInit:
                    for(int lane=0;lane<16;++lane) {
                        #pragma HLS UNROLL
                        acc[lane]=biases[og*16+lane]<<4;
                    }
                StemDot:
                    for(int k=0;k<147;++k) {
                        #pragma HLS PIPELINE II=1
                        int ky=k/21,kx=(k/3)%7,ci=k%3;
                        ap_uint<5> row=slot+1+ky;
                        if(row>=7)row-=7;
                        ap_uint<24> word=rows[row][x-6+kx];
                        ap_int<8> datum=word.range(ci*8+7,ci*8);
                        ap_uint<128> packed_weights=weights[og*147+k];
                    StemMAC:
                        for(int lane=0;lane<16;++lane) {
                            #pragma HLS UNROLL
                            ap_int<8> weight=packed_weights.range(lane*8+7,lane*8);
                            ap_int<16> product=datum*weight;
                            acc[lane]+=product;
                        }
                    }
                    // Serialize only this16-lane result as two contiguous8-lane packets.
                StemPacket:
                    for(int half=0;half<2;++half) {
                        #pragma HLS PIPELINE off
                        ap_uint<64> result=0;
                    StemEmit:
                        for(int lane=0;lane<8;++lane) {
                            #pragma HLS UNROLL
                            ap_int<8> raw=round_sat<7>(acc[half*8+lane]);
                            if(raw<0)raw=0;
                            result.range(lane*8+7,lane*8)=raw;
                        }
                        output.write(result);
                    }
                }
            }
        }
        if(slot==6)slot=0;else ++slot;
    }
}
} // namespace grouped
