#!/bin/bash
# 主升浪项目 Mac 初始化
echo "=== 主升浪 Mac Setup ==="

# Install Python dependencies
pip3 install akshare openpyxl -q

# Add cc alias
if ! grep -q "alias cc=" ~/.zshrc 2>/dev/null; then
    PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
    echo "alias cc='cd $PROJECT_DIR && claude'" >> ~/.zshrc
    echo "Added 'cc' alias to ~/.zshrc"
fi

# Verify
python3 -c "from scripts.daily.config import PROJECT_ROOT; print('Project root:', PROJECT_ROOT)"

echo ""
echo "Setup complete!"
echo "  Run: source ~/.zshrc"
echo "  Then: cc"
echo "  Or: cd $(cd "$(dirname "$0")" && pwd) && claude"
