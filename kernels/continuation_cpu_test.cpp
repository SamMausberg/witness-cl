#include "continuation_reference.hpp"
#include <random>
#include <iostream>
#include <cassert>
#include <algorithm>
int main() {
  for(unsigned seed=0;seed<200;++seed) {
    std::mt19937 rng(seed);
    size_t M=1+rng()%20,H=1+rng()%8,S=1+rng()%12,A=1+rng()%4;
    std::vector<int32_t> ns(M*H*S*A);
    std::vector<int64_t> r(ns.size()),v(M*(H+1)*S);
    for(auto& x:ns)x=rng()%S;
    for(auto& x:r)x=int(rng()%21)-10;
    for(auto& x:v)x=int(rng()%51)-25;
    auto out=continuation_lower_reference(ns,r,v,M,H,S,A);
    for(size_t q=0;q<out.size();++q) {
      size_t a=q%A,s=q/A%S,t=q/(S*A);
      std::vector<int64_t> candidates;
      for(size_t m=0;m<M;++m){size_t i=((m*H+t)*S+s)*A+a;
        candidates.push_back(r.at(i)+v.at((m*(H+1)+t+1)*S+ns.at(i))-v.at((m*(H+1)+t)*S+s));}
      assert(out.at(q)==*std::min_element(candidates.begin(),candidates.end()));
    }
  }
  bool rejected=false;
  try { continuation_lower_reference({0},{INT64_MAX},{INT64_MIN,INT64_MAX},1,1,1,1); }
  catch(const std::overflow_error&) { rejected=true; }
  assert(rejected);
  std::cout<<"200 randomized C++ continuation cases plus overflow rejection passed\n";
}
