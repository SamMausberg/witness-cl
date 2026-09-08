CXX ?= g++
NVCC ?= nvcc
.PHONY: cpu-check cuda-check clean
cpu-check:
	$(CXX) -std=c++17 -O2 -Wall -Wextra -pedantic cpu_test.cpp -o cpu_test
	./cpu_test
cuda-check:
	$(NVCC) -std=c++17 -O3 -arch=sm_90 -lineinfo witness_ops.cu cuda_test.cu -o cuda_test
	./cuda_test
	compute-sanitizer --tool memcheck ./cuda_test
	compute-sanitizer --tool racecheck ./cuda_test
clean:
	rm -f cpu_test cuda_test
