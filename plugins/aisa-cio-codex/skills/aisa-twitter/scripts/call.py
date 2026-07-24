#!/usr/bin/env python3
"""aisa-twitter wrapper"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "_shared"))
from aisa_client import main
main()
