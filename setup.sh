#!/usr/bin/env bash
# Project Setup Script
# Creates a virtual environment and installs required dependencies natively (PEP 668 compliant).

set -e

echo "=============================================="
echo "    Project Setup - Cloud Deployment Prep     "
echo "=============================================="

# Detect python command
if command -v python3 &>/dev/null; then
    PYTHON_CMD="python3"
elif command -v python &>/dev/null; then
    PYTHON_CMD="python"
else
    echo "ERROR: Python 3 could not be found."
    exit 1
fi

# Ensure Python version is >= 3.8
$PYTHON_CMD -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' || {
    echo "ERROR: Python 3.8 or higher is required."
    exit 1
}

VENV_DIR="venv"

# Create the virtual environment if it does not exist
if [ ! -d "$VENV_DIR" ]; then
    echo "--> Creating virtual environment in ./$VENV_DIR"
    $PYTHON_CMD -m venv "$VENV_DIR"
else
    echo "--> Virtual environment already exists in ./$VENV_DIR"
fi

# Activate the virtual environment
echo "--> Activating virtual environment..."
source "$VENV_DIR/bin/activate"

# Verify we are in a virtual environment now
if [ -z "$VIRTUAL_ENV" ]; then
    echo "ERROR: Failed to activate virtual environment."
    exit 1
fi

echo "--> Upgrading pip..."
pip install --upgrade pip

echo "--> Installing project dependencies from requirements.txt..."
pip install -r requirements.txt

echo "=============================================="
echo "Setup Complete!"
echo "To start the application, run the following:"
echo ""
echo "    source venv/bin/activate"
echo "    python main.py"
echo "=============================================="
