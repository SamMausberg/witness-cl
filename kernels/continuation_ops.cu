// Witness-CL v0.3 DRAFT. Not compiled, sanitized, or timed in this environment.
// Preconditions: contiguous immutable tensors; M,H,S,A > 0; ns in [0,S);
// all tensor indices fit size_t; (2*H+1)*max_abs_reward <= INT64_MAX;
// baseline_values are exact and match the SAME model family and baseline hash.
// One CTA per (time,state,action). No use for tiny families unless amortized.
#include <cuda_runtime.h>
#include <cstdint>
#include <climits>

__global__ void continuation_lower_bound(
    const int32_t* __restrict__ next_state,
    const int64_t* __restrict__ reward,
    const int64_t* __restrict__ baseline_values,
    int64_t* __restrict__ lower,
    int M, int H, int S, int A) {
  // Host must launch exactly 256 threads and H*S*A blocks.
  const size_t q = blockIdx.x;
  const int a = q % A;
  const int s = (q / A) % S;
  const int t = q / (size_t(S) * A);
  long long result = LLONG_MAX;
  for (int m = threadIdx.x; m < M; m += blockDim.x) {
    const size_t rix = ((size_t(m)*H+t)*S+s)*A+a;
    const int ns = next_state[rix];
    const size_t vbase=(size_t(m)*(H+1)+t)*S;
    const long long d=reward[rix]+baseline_values[vbase+S+ns]-baseline_values[vbase+s];
    result = result < d ? result : d;
  }
  for (int offset=16; offset>0; offset>>=1) {
    const long long x=__shfl_down_sync(0xffffffff,result,offset);
    result=result<x ? result : x;
  }
  __shared__ long long warp_min[8];
  if ((threadIdx.x&31)==0) warp_min[threadIdx.x>>5]=result;
  __syncthreads();
  if (threadIdx.x==0) {
    long long v=warp_min[0];
    for (int i=1;i<8;++i) v=v<warp_min[i] ? v : warp_min[i];
    lower[q]=v;
  }
}
