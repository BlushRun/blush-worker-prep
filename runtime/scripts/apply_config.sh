#!/bin/bash
# 热更新：修改 config.yml 后执行此脚本，不需要重启容器
#
# 用法（容器内）:
#   /app/scripts/apply_config.sh
#
# 用法（docker compose）:
#   docker compose exec comfyui-worker /app/scripts/apply_config.sh

set -e

echo "=================================================="
echo "  blush-worker 配置热更新"
echo "=================================================="
echo ""

# ── 检测环境 ──
if [ -d "/runpod-volume" ]; then
    MODELS_DIR="/runpod-volume/models"
    COMFYUI_DIR="/runpod-volume/ComfyUI"
elif [ -d "/workspace" ]; then
    MODELS_DIR="/workspace/models"
    COMFYUI_DIR="/workspace/ComfyUI"
else
    MODELS_DIR="/comfyui/models"
    COMFYUI_DIR="/comfyui"
fi

# ── 确定 config.yml 位置 ──
CONFIG_FILE=""
for path in "/runpod-volume/config.yml" "/workspace/config.yml" "/app/config.yml"; do
    if [ -f "$path" ]; then
        CONFIG_FILE="$path"
        break
    fi
done

if [ -z "$CONFIG_FILE" ]; then
    echo "错误: 找不到 config.yml"
    exit 1
fi

echo "配置: $CONFIG_FILE"
echo "模型目录: $MODELS_DIR"
echo "ComfyUI: $COMFYUI_DIR"
echo ""

# ── 同步模型 ──
echo "=================================================="
echo "  同步模型"
echo "=================================================="
echo ""
python3 /app/scripts/sync-models.py --config "$CONFIG_FILE" --models-dir "$MODELS_DIR" \
    || echo "警告: 部分模型同步失败"
echo ""

# ── 安装节点 ──
echo "=================================================="
echo "  安装节点"
echo "=================================================="
echo ""
python3 /app/scripts/install_nodes.py --config "$CONFIG_FILE" --comfyui-dir "$COMFYUI_DIR" \
    || echo "警告: 部分节点安装失败"
echo ""

# ── 更新 SHA 缓存 ──
SHA_FILE=""
if [ -d "/runpod-volume" ]; then
    SHA_FILE="/runpod-volume/.config-sha256"
elif [ -d "/workspace" ]; then
    SHA_FILE="/workspace/.config-sha256"
fi

if [ -n "$SHA_FILE" ]; then
    CURRENT_SHA=$(sha256sum "$CONFIG_FILE" | awk '{print $1}')
    echo "$CURRENT_SHA" > "$SHA_FILE"
    echo "SHA 已更新: ${CURRENT_SHA:0:16}..."
fi

echo ""
echo "=================================================="
echo "  热更新完成"
echo "=================================================="
echo ""
echo "如果新增了节点，可能需要重启 ComfyUI 才能加载:"
echo "  docker compose restart"
echo ""
