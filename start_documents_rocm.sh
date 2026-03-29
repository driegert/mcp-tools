#!/bin/bash
# Launch the document processing MCP server with ROCm GPU acceleration.
#
# The first run after a reboot will be slow (~4 min) as ROCm compiles
# GPU kernels for gfx1151. Subsequent runs use cached kernels (~10s).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ROCm environment (shared TheRock distribution from vllm-rocm)
export ROCM_PATH="/home/dave/venvs/vllm-rocm/rocm-7.11.0a20260106"
export LD_LIBRARY_PATH="${ROCM_PATH}/lib:${ROCM_PATH}/lib64"
export DEVICE_LIB_PATH="${ROCM_PATH}/llvm/amdgcn/bitcode"
export HIP_DEVICE_LIB_PATH="${ROCM_PATH}/llvm/amdgcn/bitcode"
export HSA_OVERRIDE_GFX_VERSION="11.5.1"
export PYTORCH_ROCM_ARCH="gfx1151"

exec "${SCRIPT_DIR}/.venv/bin/python" "${SCRIPT_DIR}/server_documents.py"
