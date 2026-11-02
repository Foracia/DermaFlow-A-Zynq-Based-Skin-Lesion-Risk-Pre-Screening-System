#include <fstream>
#include <iostream>
#include <stdexcept>
#include "core.h"
unsigned group_frame=0;

void stem16_boundary(hls::stream<ap_uint<24>>&,hls::stream<ap_uint<64>>&);
void check_stem_boundary(){
 std::ifstream fin("boundary_inputs.bin",std::ios::binary);
 std::ifstream ref("boundary_expected.bin",std::ios::binary);
 if(!fin||!ref)throw std::runtime_error("Stem boundary fixtures missing");
 unsigned count=0;
 for(int f=0;f<4;++f){
  hls::stream<ap_uint<24>> x;
  hls::stream<ap_uint<64>> y;
  for(int p=0;p<16384;++p){ap_uint<24> word=0;for(int c=0;c<3;++c){unsigned char v;fin.read((char*)&v,1);if(!fin)throw std::runtime_error("Boundary input short");word.range(c*8+7,c*8)=v;}x.write(word);}
  stem16_boundary(x,y);
  if(!x.empty())throw std::runtime_error("Boundary extra input");
  for(int p=0;p<32768;++p){
   if(y.empty())throw std::runtime_error("Boundary output short");auto word=y.read();
   for(int c=0;c<8;++c){unsigned char v;ref.read((char*)&v,1);if(!ref||word.range(c*8+7,c*8).to_uint()!=v)throw std::runtime_error("Boundary raw/order mismatch");++count;}
  }
  if(!y.empty())throw std::runtime_error("Boundary extra output");
 }
 char extra;if(fin.read(&extra,1)||ref.read(&extra,1)||count!=1048576)throw std::runtime_error("Boundary fixture count");
 std::cout<<"STEM16_BOUNDARY_PASS frames=4 words="<<count<<std::endl;
}
int main(){try {
 check_stem_boundary();
    std::ifstream in("inputs.bin",std::ios::binary);
    std::ifstream ref("expected.bin",std::ios::binary);
    if(!in||!ref)throw std::runtime_error("fixture open");
    hls::stream<ap_uint<24>> x;
    hls::stream<ap_uint<16>> y;
    unsigned count=0;
    for(unsigned f=0;f<4;++f){
 group_frame=f;
        for(unsigned p=0;p<16384;++p){
            ap_uint<64> pack=0;
            for(unsigned c=0;c<3;++c){unsigned char v;in.read((char*)&v,1);if(!in)throw std::runtime_error("input short");pack.range(c*8+7,c*8)=v;}
            x.write(pack);
        }
        grouped_network(x,y);
        if(!x.empty())throw std::runtime_error("input extra");
        for(unsigned p=0;p<1;++p){
            if(y.empty())throw std::runtime_error("output short");
            auto pack=y.read();
            for(unsigned c=0;c<2;++c){unsigned char v;ref.read((char*)&v,1);if(!ref)throw std::runtime_error("reference short");
                if(pack.range(c*8+7,c*8).to_uint()!=v){std::cerr<<"MISMATCH frame="<<f<<" token="<<p<<" lane="<<c<<std::endl;return 2;}++count;}
        }
        if(!y.empty())throw std::runtime_error("output extra");
        std::cout<<"GROUP_FRAME "<<f<<" PASS"<<std::endl;
    }
    char extra;if(in.read(&extra,1)||ref.read(&extra,1))throw std::runtime_error("fixture extra");
    std::cout<<"GROUP_CSIM_PASS frames=4 words="<<count<<std::endl;return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<std::endl;return 3;}}
