#pragma once
#include <fstream>
#include <vector>
#include <stdexcept>
extern unsigned group_frame;
template<int B> void group_dump(hls::stream<ap_uint<B>>& stream,const char* name){
    std::vector<ap_uint<B>> saved;
    std::ofstream f(std::string("trace_")+std::to_string(group_frame)+"_"+name+".bin",std::ios::binary);
    if(!f)throw std::runtime_error("trace open");
    while(!stream.empty()){
        auto word=stream.read();saved.push_back(word);
        for(int c=0;c<B/8;++c){unsigned char raw=word.range(c*8+7,c*8).to_uint();f.write((char*)&raw,1);}
    }
    for(auto word:saved)stream.write(word);
    if(!f || saved.empty())throw std::runtime_error("trace missing");
}
