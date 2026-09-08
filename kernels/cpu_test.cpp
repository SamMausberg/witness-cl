#include "reference.hpp"
#include <iostream>
#include <random>
int main() {
  std::mt19937 rng(1729);int tests=0;
  for(int B:{1,3,16}) for(int H:{1,31,32,33,63,64,65,257,4097}) for(int seed=0;seed<16;++seed) {
    int W=(H+31)/32;
    std::vector<int32_t> p(size_t(B)*H),a(B);
    std::vector<uint8_t> s(B);
    std::vector<uint32_t> live(size_t(B)*W);
    for(auto&x:p)x=int(rng()%17)-8;
    for(auto&x:a)x=int(rng()%17)-8;
    for(auto&x:s)x=rng()%2;
    for(auto&x:live)x=rng();
    auto r=witness_cpu::update(p,live,a,s,B,H);
    for(int b=0;b<B;++b) for(int h=0;h<H;++h) {
      bool expected=((live[size_t(b)*W+h/32]>>(h%32))&1u) && ((p[size_t(b)*H+h]==a[b])==bool(s[b]));
      if(expected!=bool((r.live[size_t(b)*W+h/32]>>(h%32))&1u)) return 1;
    }
    auto again=witness_cpu::update(p,r.live,a,s,B,H);
    if(again.live!=r.live) return 2;
    for(auto row:again.rows) if(row.changed) return 3;
    ++tests;
  }
  std::cout<<"{\"cpu_cpp_cases_passed\":"<<tests<<",\"gpu_executed\":false}\n";
}
