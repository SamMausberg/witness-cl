// CUDA DRAFT: not compiled/executed in the authoring CPU-only environment.
// Exact int32 comparisons and uint32 masks only. No FP arithmetic influences
// admission. These kernels do not validate the hypothesis-class assumptions.
#include "witness_ops.cuh"
#include <climits>
namespace witness {
constexpr int Threads=256;

template<bool Filter>
__global__ void word_kernel(const int32_t* pred,const uint32_t* live,
    const int32_t* actions,const uint8_t* success,uint32_t* next,
    WordStats* stats,int H,int W) {
  const int lane=threadIdx.x&31;
  const int w=blockIdx.x*(blockDim.x/32)+threadIdx.x/32;
  const int b=blockIdx.y;
  if(w>=W) return; // whole warp returns, never a partial ballot participation
  const int h=w*32+lane;
  const size_t index=size_t(b)*W+w;
  const uint32_t old=live[index];
  const bool eligible=h<H && ((old>>lane)&1u);
  const int32_t p=h<H ? pred[size_t(b)*H+h] : 0;
  bool keep=eligible;
  if constexpr(Filter) keep=eligible && ((p==actions[b])==(success[b]!=0));
  const uint32_t mask=__ballot_sync(0xffffffffu,keep);
  int mn=keep?p:INT_MAX,mx=keep?p:INT_MIN;
  for(int d=16;d;d/=2) {
    mn=min(mn,__shfl_down_sync(0xffffffffu,mn,d));
    mx=max(mx,__shfl_down_sync(0xffffffffu,mx,d));
  }
  if(lane==0) {
    if constexpr(Filter) next[index]=mask;
    stats[index]={__popc(mask),mn,mx,Filter ? int(mask!=old) : 0};
  }
}

__global__ void row_kernel(const WordStats* words,RowStats* rows,int W) {
  __shared__ int cnt[Threads],mn[Threads],mx[Threads],change[Threads];
  const int tid=threadIdx.x,b=blockIdx.x;
  int c=0,lo=INT_MAX,hi=INT_MIN,ch=0;
  for(int w=tid;w<W;w+=blockDim.x) {
    const WordStats s=words[size_t(b)*W+w];
    c+=s.count;lo=min(lo,s.minimum);hi=max(hi,s.maximum);ch|=s.changed;
  }
  cnt[tid]=c;mn[tid]=lo;mx[tid]=hi;change[tid]=ch;
  __syncthreads();
  for(int stride=Threads/2;stride;stride/=2) {
    if(tid<stride) {
      cnt[tid]+=cnt[tid+stride];mn[tid]=min(mn[tid],mn[tid+stride]);
      mx[tid]=max(mx[tid],mx[tid+stride]);change[tid]|=change[tid+stride];
    }
    __syncthreads();
  }
  if(tid==0) {
    const bool unanimous=cnt[0]>0 && mn[0]==mx[0];
    rows[b]={cnt[0],unanimous?mn[0]:0,int(unanimous),change[0]};
  }
}

cudaError_t filter(const int32_t* pred,const uint32_t* live,
    const int32_t* actions,const uint8_t* success,uint32_t* next,
    WordStats* words,RowStats* rows,int B,int H,cudaStream_t stream) {
  if(B<1 || B>65535 || H<1 || H>INT_MAX-31 || !pred || !live || !actions ||
     !success || !next || !words || !rows) return cudaErrorInvalidValue;
  const int W=(H+31)/32;
  word_kernel<true><<<dim3((W+7)/8,B),Threads,0,stream>>>(pred,live,actions,success,next,words,H,W);
  cudaError_t err=cudaGetLastError(); if(err!=cudaSuccess) return err;
  row_kernel<<<B,Threads,0,stream>>>(words,rows,W);
  return cudaGetLastError();
}
cudaError_t consensus(const int32_t* pred,const uint32_t* live,
    WordStats* words,RowStats* rows,int B,int H,cudaStream_t stream) {
  if(B<1 || B>65535 || H<1 || H>INT_MAX-31 || !pred || !live || !words || !rows)
    return cudaErrorInvalidValue;
  const int W=(H+31)/32;
  word_kernel<false><<<dim3((W+7)/8,B),Threads,0,stream>>>(pred,live,nullptr,nullptr,nullptr,words,H,W);
  cudaError_t err=cudaGetLastError();if(err!=cudaSuccess)return err;
  row_kernel<<<B,Threads,0,stream>>>(words,rows,W);
  return cudaGetLastError();
}
}
