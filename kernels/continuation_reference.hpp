#pragma once
#include <cstdint>
#include <stdexcept>
#include <limits>
#include <vector>
#include <cstddef>

// Scalar checked oracle for an already computed baseline continuation table.
// CUDA draft parity remains untested. This oracle uses wider intermediates.
inline std::vector<int64_t> continuation_lower_reference(
    const std::vector<int32_t>& ns, const std::vector<int64_t>& r,
    const std::vector<int64_t>& v, size_t M,size_t H,size_t S,size_t A) {
  if (!M || !H || !S || !A || ns.size()!=M*H*S*A || r.size()!=ns.size() || v.size()!=M*(H+1)*S)
    throw std::invalid_argument("invalid dimensions");
  std::vector<int64_t> out(H*S*A,std::numeric_limits<int64_t>::max());
  for(size_t m=0;m<M;++m) for(size_t t=0;t<H;++t) for(size_t s=0;s<S;++s) for(size_t a=0;a<A;++a) {
    const size_t i=((m*H+t)*S+s)*A+a, q=(t*S+s)*A+a;
    if(ns[i]<0 || size_t(ns[i])>=S) throw std::invalid_argument("invalid successor");
    const __int128 d=__int128(r[i])+v[(m*(H+1)+t+1)*S+ns[i]]-v[(m*(H+1)+t)*S+s];
    if(d<std::numeric_limits<int64_t>::min() || d>std::numeric_limits<int64_t>::max())
      throw std::overflow_error("advantage overflow");
    if(d<out[q]) out[q]=int64_t(d);
  }
  return out;
}
