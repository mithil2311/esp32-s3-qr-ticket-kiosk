#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <cstring>
namespace kiosk {
struct Scan {char token[97]{};uint64_t input_us=0;uint64_t received_us=0;};
class Scanner {
 char frame_[97]{};size_t used_=0;bool discard_=false;uint64_t first_=0,last_=0;
public:
 uint32_t corrupt=0;
 void disconnect(){if(used_||discard_)++corrupt;used_=0;discard_=false;}
 void expire(uint64_t now){if((used_||discard_)&&now-last_>1000000){++corrupt;used_=0;discard_=false;}}
 template<class Sink> void feed(const uint8_t* data,size_t n,uint64_t now,Sink sink,uint64_t source_us=0){
  expire(now);
  for(size_t i=0;i<n;++i){auto c=data[i];
   if(c=='\r'||c=='\n'){
    if(!discard_&&used_){Scan s{};std::memcpy(s.token,frame_,used_);s.input_us=first_;s.received_us=now;sink(s);}
    used_=0;discard_=false;continue;
   }
   if(!used_&&!discard_)first_=(source_us&&source_us<=now)?source_us:now;
   last_=now;
   if(c<32||c>126||used_>=96){if(!discard_)++corrupt;discard_=true;continue;}
   if(!discard_)frame_[used_++]=char(c);
  }
 }
 static bool valid(const char* s){
  if(std::strncmp(s,"TKT:",4))return false;
  size_t n=std::strlen(s+4);if(!n||n>64)return false;
  for(auto p=s+4;*p;++p)if(!((*p>='a'&&*p<='z')||(*p>='A'&&*p<='Z')||(*p>='0'&&*p<='9')||*p=='_'||*p=='-'))return false;
  return true;
 }
};
}
