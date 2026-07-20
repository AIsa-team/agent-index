#!/usr/bin/env python3
"""aisa-last30days wrapper — multi-source 30-day research"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "_shared"))
from aisa_client import AIsaClient

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", "-t", required=True)
    parser.add_argument("--deep", action="store_true")
    args = parser.parse_args()
    
    client = AIsaClient()
    # 使用 mixed search + tavily search 聚合 30 天多源数据
    print(f"🔍 Last30Days Research: {args.topic}")
    if args.deep:
        print("Mode: DEEP")
    print()
    
    # Web + scholar search
    client.search.mixed_search(args.topic)
    
    # Tavily search for additional coverage
    client.search.tavily_search(args.topic)

if __name__ == "__main__":
    main()
