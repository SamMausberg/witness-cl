#pragma once
#include <algorithm>
#include <climits>
#include <cstdint>
#include <stdexcept>
#include <vector>
namespace witness_cpu {
struct Row { int count,value,unanimous,changed; };
struct Result { std::vector<uint32_t> live; std::vector<Row> rows; };
inline Result update(const std::vector<int32_t>& pred,const std::vector<uint32_t>& live,
                     const std::vector<int32_t>& actions,const std::vector<uint8_t>& success,
                     int B,int H,bool filtering=true) {
  if(B<1 || H<1 || H>INT_MAX-31) throw std::invalid_argument("invalid dimensions");
  const int W=(H+31)/32;
  if(pred.size()!=size_t(B)*H || live.size()!=size_t(B)*W ||
    actions.size()!=size_t(B) || success.size()!=size_t(B)) throw std::invalid_argument("buffer sizes");
  Result r{std::vector<uint32_t>(live.size()),std::vector<Row>(B)};
  for(int b=0;b<B;++b) {
    int c=0,mn=INT_MAX,mx=INT_MIN,ch=0;
    for(int w=0;w<W;++w) {
      uint32_t next=0;
      for(int lane=0;lane<32;++lane) {
        const int h=w*32+lane;
        const bool active=h<H && ((live[size_t(b)*W+w]>>lane)&1u);
        const int p=h<H ? pred[size_t(b)*H+h] : 0;
        if(active && (!filtering || ((p==actions[b])==bool(success[b])))) {
          next|=uint32_t(1)<<lane;++c;mn=std::min(mn,p);mx=std::max(mx,p);
        }
      }
      r.live[size_t(b)*W+w]=next;
      ch|=filtering && next!=live[size_t(b)*W+w];
    }
    r.rows[b]={c,c>0&&mn==mx?mn:0,int(c>0&&mn==mx),ch};
  }
  return r;
}
}
