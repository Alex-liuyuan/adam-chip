#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
TIMEOUT=${TIMEOUT:-600}
mkdir -p "$ROOT/third_party"
cd "$ROOT/third_party" || exit 1

clone() {
    name=$1
    url=$2
    branch=$3
    if [ -d "$name/.git" ] || [ -f "$name/.fetched" ]; then
        printf 'ok existing %s\n' "$name"
        return 0
    fi

    rm -rf "$name"
    printf 'clone %s\n' "$name"
    case "$url" in
        https://gitee.com/*)
            fetch_tarball "$name" "$url" "$branch"
            return $?
            ;;
    esac
    timeout "$TIMEOUT" git -c http.version=HTTP/1.1 clone --depth 1 --single-branch "$url" "$name" || {
        rc=$?
        if [ -d "$name/.git" ]; then
            printf 'retry checkout %s\n' "$name"
            timeout "$TIMEOUT" git -C "$name" restore --source=HEAD :/ && return 0
        fi
        printf 'git failed %s rc=%s; trying tarball\n' "$name" "$rc"
        fetch_tarball "$name" "$url" "$branch"
    }
}

clone_sparse() {
    name=$1
    url=$2
    branch=$3
    shift 3
    if [ -f "$name/.fetched" ]; then
        printf 'ok existing %s\n' "$name"
        return 0
    fi
    if [ -d "$name/.git" ]; then
        printf 'resume sparse %s\n' "$name"
        timeout "$TIMEOUT" git -C "$name" sparse-checkout set "$@" &&
            touch "$name/.fetched"
        return $?
    fi

    rm -rf "$name"
    printf 'clone %s sparse\n' "$name"
    timeout "$TIMEOUT" git -c http.version=HTTP/1.1 clone --depth 1 --filter=blob:none --sparse --single-branch --branch "$branch" "$url" "$name" &&
        timeout "$TIMEOUT" git -C "$name" sparse-checkout set "$@" &&
        touch "$name/.fetched"
}

clone_pinned_sparse() {
    name=$1
    url=$2
    revision=$3
    shift 3
    if [ -d "$name/.git" ]; then
        actual=$(git -C "$name" rev-parse HEAD 2>/dev/null || true)
        if [ "$actual" != "$revision" ]; then
            printf 'refuse revision drift %s expected=%s actual=%s\n' "$name" "$revision" "$actual"
            return 1
        fi
        dirty=$(git -C "$name" status --porcelain --untracked-files=no)
        if [ -n "$dirty" ]; then
            printf 'refuse tracked changes %s\n' "$name"
            return 1
        fi
        timeout "$TIMEOUT" git -C "$name" sparse-checkout set "$@"
        return $?
    fi

    printf 'clone %s pinned sparse %s\n' "$name" "$revision"
    timeout "$TIMEOUT" git -c http.version=HTTP/1.1 clone --filter=blob:none --sparse --no-checkout "$url" "$name" &&
        timeout "$TIMEOUT" git -C "$name" fetch --depth 1 origin "$revision" &&
        timeout "$TIMEOUT" git -C "$name" sparse-checkout set "$@" &&
        timeout "$TIMEOUT" git -C "$name" checkout --detach "$revision"
}

fetch_rt_thread() {
    name=rt-thread
    url=https://github.com/RT-Thread/rt-thread.git
    if [ -d "$name/.git" ] || [ -f "$name/.fetched" ]; then
        printf 'ok existing %s\n' "$name"
        return 0
    fi

    rm -rf "$name" "$name.tar.gz"
    printf 'clone %s sparse\n' "$name"
    timeout "$TIMEOUT" git -c http.version=HTTP/1.1 clone --depth 1 --filter=blob:none --sparse "$url" "$name" &&
        timeout "$TIMEOUT" git -C "$name" sparse-checkout set components include src libcpu/risc-v bsp/gd32/risc-v bsp/hifive1 bsp/k210 tools &&
        touch "$name/.fetched"
}

fetch_tarball() {
    name=$1
    url=$2
    branch=$3
    case "$url" in
        https://gitee.com/*)
            api=$(printf '%s\n' "$url" | sed -E "s#https://gitee.com/([^/]+)/(.+)(\\.git)?\$#https://gitee.com/\\1/\\2/repository/archive/$branch.tar.gz#; s#\\.git/repository#/repository#")
            ;;
        *)
            api=$(printf '%s\n' "$url" | sed -E "s#https://github.com/([^/]+)/(.+)(\\.git)?\$#https://codeload.github.com/\\1/\\2/tar.gz/refs/heads/$branch#; s#\\.git/tar.gz#\/tar.gz#")
            ;;
    esac
    tmp="$name.tar.gz"

    rm -rf "$name"
    mkdir -p "$name"
    timeout "$TIMEOUT" curl --http1.1 -L --fail -C - --retry 20 --retry-all-errors --retry-delay 5 --connect-timeout 30 --max-time "$TIMEOUT" "$api" -o "$tmp" || {
        rc=$?
        printf 'failed %s tarball rc=%s\n' "$name" "$rc"
        rm -rf "$name"
        return "$rc"
    }
    tar -xzf "$tmp" -C "$name" --strip-components 1
    rm -f "$tmp"
    touch "$name/.fetched"
}

fetch_renode_portable() {
    name=renode_portable
    url=https://builds.renode.io/renode-latest.linux-portable.tar.gz
    tmp=renode-latest.linux-portable.tar.gz
    if [ -x "$name/renode" ]; then
        printf 'ok existing %s\n' "$name"
        return 0
    fi

    rm -rf "$name" "$tmp"
    mkdir -p "$name"
    printf 'download %s\n' "$name"
    timeout "$TIMEOUT" curl --http1.1 -L --fail -C - --retry 20 --retry-all-errors --retry-delay 5 --connect-timeout 30 --max-time "$TIMEOUT" "$url" -o "$tmp" || {
        rc=$?
        printf 'failed %s rc=%s\n' "$name" "$rc"
        rm -rf "$name"
        return "$rc"
    }
    tar -xzf "$tmp" -C "$name" --strip-components 1
    rm -f "$tmp"
    touch "$name/.fetched"
}

fetch_k230_rtsmart_toolchain() {
    name=k230-toolchain
    archive=riscv64-unknown-linux-musl-rv64imafdcv-lp64d-20230420.tar.bz2
    url=https://kendryte-download.canaan-creative.com/k230/toolchain/$archive
    expected=e6c0ce95844595eb0153db8dfaa74bcb
    compiler=$name/riscv64-linux-musleabi_for_x86_64-pc-linux-gnu/bin/riscv64-unknown-linux-musl-gcc
    if [ -x "$compiler" ]; then
        printf 'ok existing %s\n' "$name"
        return 0
    fi
    mkdir -p "$name"
    timeout "$TIMEOUT" curl --http1.1 -L --fail -C - --retry 20 --retry-all-errors --retry-delay 5 --connect-timeout 30 --max-time "$TIMEOUT" "$url" -o "$name/$archive" || return $?
    actual=$(md5sum "$name/$archive" | awk '{print $1}')
    if [ "$actual" != "$expected" ]; then
        printf 'refuse K230 RT-Smart toolchain hash expected=%s actual=%s\n' "$expected" "$actual"
        return 1
    fi
    tar -xjf "$name/$archive" -C "$name"
}

install_qimeng_bridge() {
    name=$1
    bridge="$ROOT/integrations/qimeng/$name.json"
    if [ -f "$bridge" ] && [ -d "$name" ]; then
        cp "$bridge" "$name/ADAM_INTEGRATION.json"
    fi
}

fetch_rt_thread
clone tvm https://github.com/apache/tvm.git main
clone onnx https://github.com/onnx/onnx.git main
clone tflite-micro https://github.com/tensorflow/tflite-micro.git main
clone rtthread-micropython https://github.com/RT-Thread-packages/micropython.git master
clone kendryte-standalone-sdk https://github.com/kendryte/kendryte-standalone-sdk.git master
fetch_renode_portable
clone NMSIS https://github.com/Nuclei-Software/NMSIS.git master
clone riscv-tests https://github.com/riscv-software-src/riscv-tests.git master
clone mlperf-tiny https://github.com/mlcommons/tiny.git master
clone cppcheck https://github.com/cppcheck-opensource/cppcheck.git main
clone_pinned_sparse micropython-upstream https://github.com/micropython/micropython.git 06bcfd5b74c6d275ae0991a19dab8704299e4e05 py tests tools
clone_pinned_sparse micropython-stubber https://github.com/Josverl/micropython-stubber.git 140b614a306e8ce76214ed62bc0da3a0c86038bd data/schema docs mip/v6 src/stubber/board
clone_pinned_sparse openmv https://github.com/openmv/openmv.git be63fec4fba63accdb47f2c4ffbf84017555e538 common drivers/sensors lib/imlib modules ports protocol

if [ "${INCLUDE_PLATFORM_BACKENDS:-0}" = "1" ]; then
    clone_pinned_sparse k230-sdk https://github.com/kendryte/k230_sdk.git 7e302f733311d284be255f0d81d3463b6ae6ee6d board configs src/big/rt-smart/kernel src/common/opensbi src/little/uboot tools
    clone_pinned_sparse canmv-k230 https://github.com/kendryte/canmv_k230.git c05f7f56e7d634760d0ae8c57a7d81607f8e4823 boards/k230_canmv_v3p0 configs src tools
    fetch_k230_rtsmart_toolchain
fi

if [ "${INCLUDE_DEFERRED:-0}" = "1" ]; then
    clone_sparse llvm-project https://github.com/llvm/llvm-project.git main llvm/include llvm/lib/Target/RISCV mlir/include cmake
    clone riscv-gnu-toolchain https://github.com/riscv-collab/riscv-gnu-toolchain.git master
    clone renode https://github.com/renode/renode.git master
    clone_sparse onnxruntime https://github.com/microsoft/onnxruntime.git main include onnxruntime/core/session onnxruntime/core/providers/cpu cmake
    clone_sparse tinyusb https://github.com/hathach/tinyusb.git master src hw/bsp examples/device
    clone wujian100_open https://github.com/T-head-Semi/wujian100_open.git master
    clone tamago https://github.com/usbarmory/tamago.git master
fi

if [ "${INCLUDE_QIMENG:-0}" = "1" ]; then
    clone QiMeng-GEMM https://github.com/QiMeng-IPRC/QiMeng-GEMM.git main
    clone QiMeng-TensorOp https://github.com/QiMeng-IPRC/QiMeng-TensorOp.git main
    clone QiMeng-Kernel https://github.com/QiMeng-IPRC/QiMeng-Kernel.git main
    clone QiMeng-Attention https://github.com/QiMeng-IPRC/QiMeng-Attention.git main
    clone QiMeng-NeuComBack https://github.com/QiMeng-IPRC/QiMeng-NeuComBack.git main
    clone QiMeng-Xpiler https://github.com/QiMeng-IPRC/QiMeng-Xpiler.git main
    clone QiMeng-MuPa https://github.com/QiMeng-IPRC/QiMeng-MuPa.git main
    clone QiMeng-SALV https://github.com/QiMeng-IPRC/QiMeng-SALV.git main
    for name in QiMeng-GEMM QiMeng-TensorOp QiMeng-Kernel QiMeng-Attention QiMeng-NeuComBack QiMeng-Xpiler QiMeng-MuPa QiMeng-SALV; do
        install_qimeng_bridge "$name"
    done
fi
