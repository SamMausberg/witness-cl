// Independent complete-machine interpreter. No symbolic or probability claim.
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <utility>
#include <vector>
using I=std::int64_t;
static int bounded(int low,int high){int x;if(!(std::cin>>x)||x<low||x>high)throw std::runtime_error("invalid bounded input");return x;}
int main(){try{
 const int cases=bounded(1,10000);
 for(int c=0;c<cases;c++){
  const int K=bounded(1,16), A=bounded(1,8), O=bounded(1,4), H=bounded(1,8);
  std::vector<std::pair<int,int>> edges;
  for(int i=0;i<K*A;i++){int s=bounded(0,K-1),o=bounded(0,O-1);edges.emplace_back(s,o);}
  std::vector<I> rewards;for(int i=0;i<O;i++)rewards.push_back(bounded(-1000000,1000000));
  I totals[2]={0,0};
  for(int p=0;p<2;p++){
   int state=0,index=0,width=1;
   for(int t=0;t<H;t++){
    int action=-1;
    for(int i=0;i<width;i++){int a=bounded(0,A-1);if(i==index)action=a;}
    auto edge=edges.at(state*A+action);
    state=edge.first;index=index*O+edge.second;
    totals[p]+=rewards.at(edge.second); // abs sum <= 8e6 by input contract
    width*=O;
   }
  }
  std::cout<<totals[0]-totals[1]<<'\n';
 }
 return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 2;}}
