from pathlib import Path
import random,subprocess,sys,tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from witness_cl.latent import Machine,Program,value
root=Path(__file__).resolve().parents[1]
rng=random.Random(260908);data=['400'];expected=[]
for _ in range(400):
    k=rng.randint(1,4);a=rng.randint(1,3);o=rng.randint(1,3);h=rng.randint(1,5)
    m=Machine(k,a,o,tuple((rng.randrange(k),rng.randrange(o)) for _ in range(k*a)))
    rewards=tuple(rng.randint(-1000000,1000000) for _ in range(o))
    ps=[Program(o,tuple(tuple(rng.randrange(a) for _ in range(o**t)) for t in range(h))) for _ in range(2)]
    row=[k,a,o,h]+[x for edge in m.table for x in edge]+list(rewards)+[v for p in ps for level in p.levels for v in level]
    data.append(' '.join(map(str,row)));expected.append(value(m,ps[0],rewards)-value(m,ps[1],rewards))
with tempfile.TemporaryDirectory() as d:
    exe=str(Path(d)/'latent_reference')
    subprocess.run(['g++','-std=c++17','-O2','-Wall','-Wextra','-Werror','-fsanitize=undefined',str(root/'kernels/latent_reference.cpp'),'-o',exe],check=True)
    result=subprocess.run([exe],input='\n'.join(data)+'\n',capture_output=True,text=True,check=True)
    actual=list(map(int,result.stdout.split()))
    assert actual==expected
    bad=subprocess.run([exe],input='1\n1 1 1 1\n0 0\n1000001\n0\n0\n',capture_output=True,text=True)
    assert bad.returncode==2
print('400 randomized Python/C++ continuation pairs passed; reward-range rejection passed; UBSan enabled.')
