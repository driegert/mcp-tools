# ROCm GPU Acceleration for Document Processing

## Current State

- **Server**: lilbuddy (Ryzen AI Max+ 395, Radeon 8060S iGPU, gfx1151)
- **Processing**: marker-pdf runs on CPU only (32 threads)
- **Problem**: Conversion times are very long, especially with `force_ocr=True`
- **Why no GPU**: PyTorch falls back to CPU because no CUDA/ROCm is detected

## Goal

Enable marker-pdf to use the AMD iGPU via ROCm for significantly faster PDF conversion.

## Hardware

- **CPU**: AMD Ryzen AI Max+ 395 (32 threads)
- **iGPU**: Radeon 8060S (RDNA 3.5, gfx1151)
- **Memory**: Unified memory (up to 128GB shared between CPU and iGPU)
- **Advantage**: Unified memory means no CPU↔GPU transfer overhead for large models

## Requirements

### 1. ROCm Installation

- Requires ROCm 6.x+ (check for gfx1151 support in release notes)
- Install ROCm runtime and libraries on lilbuddy
- Verify with `rocminfo` and `rocm-smi`
- May need `HSA_OVERRIDE_GFX_VERSION` environment variable if gfx1151 isn't natively listed
  - Likely value: `HSA_OVERRIDE_GFX_VERSION=11.5.1` or nearest supported target

### 2. PyTorch ROCm Build

- Install PyTorch built for ROCm (not the default CUDA or CPU builds)
- `pip install torch --index-url https://download.pytorch.org/whl/rocm6.x`
- Verify: `python -c "import torch; print(torch.cuda.is_available())"` should return `True`
  (ROCm presents through PyTorch's CUDA interface via HIP)

### 3. marker-pdf Compatibility

- No code changes needed in marker-pdf or server_documents.py
- PyTorch auto-detects ROCm as "cuda" — marker's device selection (`surya/settings.py`) will pick it up
- Models will use `torch.float16` on GPU automatically

### 4. systemd Service Update

If `HSA_OVERRIDE_GFX_VERSION` is needed, add to the service file:

```ini
[Service]
Environment=HSA_OVERRIDE_GFX_VERSION=11.5.1
```

## Risks and Considerations

- **gfx1151 is very new** — ROCm support for RDNA 3.5 iGPUs may be experimental
- **iGPU ROCm support has historically been less stable** than discrete GPU support
- **Kernel driver compatibility** — ROCm requires specific `amdgpu` kernel driver versions
- **Regression risk** — branch the code before making changes to the Python environment
- **Vulkan is NOT an option** — PyTorch does not support Vulkan as a compute backend

## Implementation Steps

1. Branch the mcp-tools repo on lilbuddy (preserve working CPU-only state)
2. Check ROCm release notes for gfx1151 / RDNA 3.5 support status
3. Install ROCm runtime on lilbuddy
4. Verify GPU is detected: `rocminfo`, `rocm-smi`
5. Install PyTorch ROCm build in the mcp-tools venv
6. Verify PyTorch sees the GPU: `python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"`
7. Test marker-pdf conversion on a small PDF
8. Benchmark: compare CPU vs GPU conversion times
9. If `HSA_OVERRIDE_GFX_VERSION` is needed, add it to the systemd service
10. Merge branch if stable

## Verification

```bash
# Quick benchmark: time a conversion with and without GPU
time python -c "
from server_documents import mcp, get_model_dict
from marker.converters.pdf import PdfConverter
from marker.config.parser import ConfigParser
import torch
print(f'Device: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"CPU\"}')
# run a test conversion...
"
```

## References

- ROCm supported GPUs: https://rocm.docs.amd.com/en/latest/release/gpu_os_support.html
- PyTorch ROCm builds: https://pytorch.org/get-started/locally/
- HSA_OVERRIDE_GFX_VERSION usage: https://github.com/ROCm/ROCm/issues
