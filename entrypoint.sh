#!/bin/sh
set -e
python3 -c "
import os, sys
sys.path.insert(0, '/app')
from src.main import run_pipeline
run_pipeline()
"
