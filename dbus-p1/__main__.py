#!/usr/bin/python3

import asyncio
import sys
import os.path

extdir = os.path.join(os.path.dirname(os.path.realpath(__file__)), "ext")
sys.path.insert(1, os.path.join(extdir, "aiovelib"))

from .bridge import P1DbusBridge


async def main():
    bridge = P1DbusBridge("/dev/ttyP1")
    await bridge.run()


asyncio.run(main())
