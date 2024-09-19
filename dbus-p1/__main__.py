#!/usr/bin/python3

import argparse
import asyncio
import sys
import os.path

extdir = os.path.join(os.path.dirname(os.path.realpath(__file__)), "ext")
sys.path.insert(1, os.path.join(extdir, "aiovelib"))

from .bridge import P1DbusBridge

parser = argparse.ArgumentParser(prog='victron-p1-gridmeter')
parser.add_argument('-p', '--port', default='/dev/ttyP1',
    help='Serial tty device connected to the gridmeter P1 port [default: %(default)s]')
args = parser.parse_args()

bridge = P1DbusBridge(args.port)
asyncio.run(bridge.run())
