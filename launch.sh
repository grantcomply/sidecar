#!/bin/bash
cd "$(dirname "$0")"
python3 main.py || {
    echo ""
    echo "Failed to launch. Make sure Python 3.10+ is installed and dependencies are set up:"
    echo "  pip install -r requirements.txt"
    read -p "Press Enter to close..."
}
