#!/usr/bin/env python3
"""
aisa-marketpulse — wrapper for AIsa financial data.
Usage: python3 this_script.py <action> --ticker <TICKER> [options]
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "_shared"))
from aisa_client import main
main()
