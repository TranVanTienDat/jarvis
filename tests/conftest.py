"""
Pytest configuration and shared fixtures.
"""
import sys
import os

# Ensure project root is on sys.path so both `client` and `server` packages resolve
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
