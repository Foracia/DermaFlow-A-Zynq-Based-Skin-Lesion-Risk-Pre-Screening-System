#pragma once
#include "ap_int.h"
#include "hls_stream.h"
// Project-owned raster/group schedule. Numerical source: frozen v12 legacy8.
// Exact integer products/prefix sums replace redundant fractional zero bits.
namespace grouped {
template<int SHIFT> ap_int<8> round_sat(ap_int<32> value) {
    static_assert(SHIFT>0 && SHIFT<24,"Proven positive shift only");
    ap_int<32> q=value>>SHIFT;
    ap_uint<SHIFT> rem=value.range(SHIFT-1,0);
    const ap_uint<SHIFT> half=ap_uint<SHIFT>(1)<<(SHIFT-1);
    if(rem>half || (rem==half && q[0])) ++q;
    if(q>127)return 127;
    if(q< -128)return -128;
    return ap_int<8>(q);
}

template<int H,int W,int CI,int CO,int K,int S,int PAD,int PI,int PO,int BSHIFT,int SHIFT>
void conv(hls::stream<ap_uint<8*PI>>& input,hls::stream<ap_uint<8*PO>>& output,
          const ap_uint<8*PO> weights[CO/PO*K*K*CI],const ap_int<32> biases[CO]) {
    static_assert(CI%PI==0 && CO%PO==0,"Full groups required");
    const int PW=W+2*PAD,PH=H+2*PAD,CG=CI/PI,D=K*K*CI;
    static ap_uint<8*PI> rows[K][PW*CG];
    #pragma HLS ARRAY_PARTITION variable=rows complete dim=1
    #pragma HLS BIND_STORAGE variable=rows type=ram_s2p impl=bram
    #pragma HLS BIND_STORAGE variable=weights type=rom_1p impl=bram
    #pragma HLS INLINE off
    ap_uint<4> slot=0;
Row:
    for(int y=0;y<PH;++y) {
Column:
        for(int x=0;x<PW;++x) {
            #pragma HLS PIPELINE off
LoadGroups:
            for(int g=0;g<CG;++g) {
                #pragma HLS PIPELINE II=1
                ap_uint<8*PI> pack=0;
                if(y>=PAD && y<H+PAD && x>=PAD && x<W+PAD)pack=input.read();
                rows[slot][x*CG+g]=pack;
            }
            if(y>=K-1 && x>=K-1 && (y-K+1)%S==0 && (x-K+1)%S==0) {
OutputGroup:
                for(int og=0;og<CO/PO;++og) {
                    #pragma HLS PIPELINE off
                    ap_int<32> acc[PO];
                    #pragma HLS ARRAY_PARTITION variable=acc complete
Init:
                    for(int lane=0;lane<PO;++lane) {
                        #pragma HLS UNROLL
                        acc[lane]=biases[og*PO+lane]<<BSHIFT;
                    }
Dot:
                    for(int k=0;k<D;++k) {
                        #pragma HLS PIPELINE II=1
                        int ky=k/(K*CI),kx=(k/CI)%K,ci=k%CI;
                        ap_uint<5> row=slot+1+ky;
                        if(row>=K)row-=K;
                        ap_uint<8*PI> pack=rows[row][(x-K+1+kx)*CG+ci/PI];
                        ap_int<8> datum=pack.range((ci%PI)*8+7,(ci%PI)*8);
                        ap_uint<8*PO> word=weights[og*D+k];
MAC:
                        for(int lane=0;lane<PO;++lane) {
                            #pragma HLS UNROLL
                            ap_int<8> weight=word.range(lane*8+7,lane*8);
                            ap_int<16> product=datum*weight;
                            acc[lane]+=product;
                        }
                    }
                    ap_uint<8*PO> result=0;
Emit:
                    for(int lane=0;lane<PO;++lane) {
                        #pragma HLS UNROLL
                        ap_int<8> raw=round_sat<SHIFT>(acc[lane]);
                        if(raw<0)raw=0; // ReLU after the original Conv round/saturate.
                        result.range(lane*8+7,lane*8)=raw;
                    }
                    output.write(result);
                }
            }
        }
        if(slot==K-1)slot=0;else ++slot;
    }
}
} // namespace grouped

#include "ap_fixed.h"
namespace grouped {
template<int H,int W,int C,int K,int S,int PAD,int G>
void pool(hls::stream<ap_uint<8*G>>& input,hls::stream<ap_uint<8*G>>& output){
    const int PW=W+2*PAD,PH=H+2*PAD,CG=C/G;
    static ap_uint<8*G> rows[K][PW*CG];
    #pragma HLS ARRAY_PARTITION variable=rows complete dim=1
    #pragma HLS BIND_STORAGE variable=rows type=ram_s2p impl=bram
    #pragma HLS INLINE off
    ap_uint<3> slot=0;
PoolRow:
    for(int y=0;y<PH;++y){
    PoolColumn:
        for(int x=0;x<PW;++x){
            #pragma HLS PIPELINE off
        PoolGroup:
            for(int g=0;g<CG;++g){
                #pragma HLS PIPELINE off
                ap_uint<8*G> pack=0;
                for(int l=0;l<G;++l){
                    #pragma HLS UNROLL
                    pack.range(l*8+7,l*8)=128;
                }
                if(y>=PAD && y<H+PAD && x>=PAD && x<W+PAD)pack=input.read();
                rows[slot][x*CG+g]=pack;
                if(y>=K-1 && x>=K-1 && (y-K+1)%S==0 && (x-K+1)%S==0){
                    ap_int<8> best[G];
                    #pragma HLS ARRAY_PARTITION variable=best complete
                    for(int l=0;l<G;++l){
                        #pragma HLS UNROLL
                        best[l]=-128;
                    }
                PoolWindow:
                    for(int k=0;k<K*K;++k){
                        #pragma HLS PIPELINE II=1
                        ap_uint<4> row=slot+1+k/K;
                        if(row>=K)row-=K;
                        auto word=rows[row][(x-K+1+k%K)*CG+g];
                        for(int l=0;l<G;++l){
                            #pragma HLS UNROLL
                            ap_int<8> value=word.range(l*8+7,l*8);
                            if(value>best[l])best[l]=value;
                        }
                    }
                    ap_uint<8*G> result=0;
                    for(int l=0;l<G;++l){
                        #pragma HLS UNROLL
                        result.range(l*8+7,l*8)=best[l];
                    }
                    output.write(result);
                }
            }
        }
        if(slot==K-1)slot=0;else ++slot;
    }
}

template<int G> void gap(hls::stream<ap_uint<8*G>>& input,hls::stream<ap_uint<8*G>>& output){
    #pragma HLS INLINE off
    ap_int<14> sums[128];
    #pragma HLS ARRAY_PARTITION variable=sums cyclic factor=G
    #pragma HLS BIND_STORAGE variable=sums type=ram_2p impl=lutram
GapPixels:
    for(int p=0;p<64;++p){
    GapGroups:
        for(int g=0;g<128/G;++g){
            #pragma HLS PIPELINE II=1
            auto pack=input.read();
            for(int l=0;l<G;++l){
                #pragma HLS UNROLL
                ap_int<8> value=pack.range(l*8+7,l*8);
                if(p==0)sums[g*G+l]=value;else sums[g*G+l]+=value;
            }
        }
    }
GapOutput:
    for(int g=0;g<128/G;++g){
        #pragma HLS PIPELINE II=1
        ap_uint<8*G> result=0;
        const unsigned denominator=64;
        for(int l=0;l<G;++l){
            #pragma HLS UNROLL
            ap_fixed<14,10,AP_RND_CONV,AP_SAT> compact;
            compact.range()=sums[g*G+l].range();
            ap_fixed<48,24,AP_RND_CONV,AP_SAT> restored=compact;
            ap_fixed<8,3,AP_RND_CONV,AP_SAT> value=restored/denominator;
            result.range(l*8+7,l*8)=value.range();
        }
        output.write(result);
    }
}

template<int G> void head(hls::stream<ap_uint<8*G>>& input,hls::stream<ap_uint<16>>& output,
                         const ap_uint<16> weights[128],const ap_int<8> bias[2]){
    #pragma HLS INLINE off
    #pragma HLS BIND_STORAGE variable=weights type=rom_1p impl=bram
    ap_int<32> acc0=0,acc1=0;
HeadGroups:
    for(int g=0;g<128/G;++g){
        #pragma HLS PIPELINE off
        auto pack=input.read();
    HeadLanes:
        for(int l=0;l<G;++l){
            #pragma HLS PIPELINE II=1
            ap_int<8> value=pack.range(l*8+7,l*8);
            auto word=weights[g*G+l];
            ap_int<8> w0=word.range(7,0),w1=word.range(15,8);
            ap_int<16> p0=value*w0,p1=value*w1;
            acc0+=p0;acc1+=p1;
        }
    }
    // FC F12 exact -> original F24 -> Add_0 F7 bias -> signed8/3 output.
    // No intermediate FC saturation is reached (prefix bound checked in preparation).
    acc0+=ap_int<32>(bias[0])<<5;acc1+=ap_int<32>(bias[1])<<5;
    ap_uint<16> result=0;
    result.range(7,0)=round_sat<7>(acc0);
    result.range(15,8)=round_sat<7>(acc1);
    output.write(result);
}
} // namespace grouped
