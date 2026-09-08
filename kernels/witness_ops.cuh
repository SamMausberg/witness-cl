#pragma once
#include <cuda_runtime.h>
#include <stdint.h>
namespace witness {
struct WordStats { int count, minimum, maximum, changed; };
struct RowStats { int count, value, unanimous, changed; };
// All buffers belong to this invocation. No shape-only cache, global mutable
// workspace, or allocation occurs in these calls. Caller controls stream order.
cudaError_t filter(const int32_t* predictions, const uint32_t* live,
    const int32_t* actions, const uint8_t* success, uint32_t* next,
    WordStats* words, RowStats* rows, int batch, int hypotheses, cudaStream_t stream);
cudaError_t consensus(const int32_t* query_predictions,const uint32_t* live,
    WordStats* words,RowStats* rows,int batch,int hypotheses,cudaStream_t stream);
}
