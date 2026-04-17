#!/bin/bash
# 在官方 /start.sh 之前运行
# 读取 config.yml，自动下载缺失模型、安装缺失节点

set -e

echo "=================================================="
echo "  blush-worker pre-start"
echo "=================================================="

# ── 检测模型目录 ──
if [ -d "/runpod-volume" ]; then
    MODELS_DIR="/runpod-volume/models"
elif [ -d "/workspace" ]; then
    MODELS_DIR="/workspace/models"
else
    MODELS_DIR="/comfyui/models"
fi
mkdir -p "$MODELS_DIR"

# ── 确定 config.yml 位置 ──
CONFIG_FILE=""
if [ -f "/runpod-volume/config.yml" ]; then
    CONFIG_FILE="/runpod-volume/config.yml"
elif [ -f "/workspace/config.yml" ]; then
    CONFIG_FILE="/workspace/config.yml"
elif [ -f "/app/config.yml" ]; then
    CONFIG_FILE="/app/config.yml"
fi

if [ -z "$CONFIG_FILE" ]; then
    echo "没有找到 config.yml，跳过模型同步"
    echo "=================================================="
    exec /start.sh "$@"
fi

echo "配置: $CONFIG_FILE"
echo "模型目录: $MODELS_DIR"

# ── SHA 缓存：config 没变就跳过 ──
SHA_FILE=""
if [ -d "/runpod-volume" ]; then
    SHA_FILE="/runpod-volume/.config-sha256"
elif [ -d "/workspace" ]; then
    SHA_FILE="/workspace/.config-sha256"
fi

CURRENT_SHA=$(sha256sum "$CONFIG_FILE" | awk '{print $1}')
SKIP_MODEL_SYNC=0

if [ -n "$SHA_FILE" ] && [ -f "$SHA_FILE" ]; then
    STORED_SHA=$(cat "$SHA_FILE" 2>/dev/null || echo "")
    if [ "$CURRENT_SHA" = "$STORED_SHA" ]; then
        echo "config.yml 未变更，跳过模型同步 (SHA: ${CURRENT_SHA:0:16}...)"
        SKIP_MODEL_SYNC=1
    fi
    if [ "$SKIP_MODEL_SYNC" -eq 0 ]; then
        echo "config.yml 已变更，执行同步..."
    fi
else
    echo "首次运行，执行同步..."
fi

# ── 同步模型 ──
echo ""
if [ "$SKIP_MODEL_SYNC" -eq 0 ]; then
    python3 /app/scripts/sync-models.py --config "$CONFIG_FILE" --models-dir "$MODELS_DIR" \
        || echo "警告: 部分模型同步失败"
fi

# ── 安装自定义节点（支持版本锁定）──
echo ""
python3 /app/scripts/install_nodes.py --config "$CONFIG_FILE" \
    || echo "警告: 部分节点安装失败"

# ── 更新 SHA 缓存 ──
if [ -n "$SHA_FILE" ]; then
    echo "$CURRENT_SHA" > "$SHA_FILE"
    echo ""
    echo "SHA 已更新: ${CURRENT_SHA:0:16}..."
    echo "下次启动如 config.yml 未变更将跳过模型同步"
fi

echo "=================================================="
echo ""

# ── 交给官方启动流程 ──
exec /start.sh "$@"
