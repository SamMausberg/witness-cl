// Standalone GH200 correctness runner. Not executed by the authoring environment.
#include "witness_ops.cuh"
#include "reference.hpp"
#include <iostream>
#include <random>
#include <cstdlib>
#define CHECK(x) do{cudaError_t e=(x);if(e!=cudaSuccess){std::cerr<<cudaGetErrorString(e)<<" at "<<__LINE__<<"\n";std::exit(1);}}while(0)
template<class T> struct Buffer {
  T* p=nullptr; size_t count;
  explicit Buffer(size_t n):count(n){CHECK(cudaMalloc(reinterpret_cast<void**>(&p),sizeof(T)*n));}
  ~Buffer(){cudaFree(p);}
  Buffer(const Buffer&)=delete;Buffer& operator=(const Buffer&)=delete;
  void set(const std::vector<T>& v){CHECK(cudaMemcpy(p,v.data(),sizeof(T)*count,cudaMemcpyHostToDevice));}
  std::vector<T> get(){std::vector<T> v(count);CHECK(cudaMemcpy(v.data(),p,sizeof(T)*count,cudaMemcpyDeviceToHost));return v;}
};
int main(){
  std::mt19937 rng(1729);int cases=0;
  for(int B:{1,3,16})for(int H:{1,31,32,33,65,257,4097})for(int seed=0;seed<16;++seed){
    const int W=(H+31)/32;
    std::vector<int32_t> p(size_t(B)*H),a(B);std::vector<uint8_t>s(B);
    std::vector<uint32_t>l(size_t(B)*W);
    for(auto&x:p)x=int(rng()%17)-8;for(auto&x:a)x=int(rng()%17)-8;
    for(auto&x:s)x=rng()%2;for(auto&x:l)x=rng();
    if(seed==0)std::fill(l.begin(),l.end(),0); // empty unanimity regression
    if(seed==1)std::fill(p.begin(),p.end(),INT_MIN); // reduction sentinel regression
    if(seed==2)std::fill(p.begin(),p.end(),INT_MAX);
    Buffer<int32_t>dp(p.size()),da(a.size());Buffer<uint8_t>ds(s.size());
    Buffer<uint32_t>dl(l.size()),dn(l.size());Buffer<witness::WordStats>dw(l.size());Buffer<witness::RowStats>dr(B);
    dp.set(p);da.set(a);ds.set(s);dl.set(l);
    for(bool filter:{true,false}){
      if(filter)CHECK(witness::filter(dp.p,dl.p,da.p,ds.p,dn.p,dw.p,dr.p,B,H,nullptr));
      else CHECK(witness::consensus(dp.p,dl.p,dw.p,dr.p,B,H,nullptr));
      CHECK(cudaDeviceSynchronize());auto expected=witness_cpu::update(p,l,a,s,B,H,filter);auto actual=dr.get();
      if(filter && dn.get()!=expected.live)return 2;
      for(int b=0;b<B;++b){auto x=actual[b];auto y=expected.rows[b];
        if(x.count!=y.count||x.value!=y.value||x.unanimous!=y.unanimous||x.changed!=y.changed)return 3;}
    }
    ++cases;
  }
  std::cout<<"{\"cuda_cases_passed\":"<<cases<<"}\n";
}
