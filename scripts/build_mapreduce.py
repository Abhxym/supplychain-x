"""Compile the C++ mapper and reducer for the Hadoop containers.

    python scripts/build_mapreduce.py

Builds inside a throwaway Alpine container, so no compiler is needed on Windows.
Linked statically: the Hadoop image is CentOS 7 with an old C library, and a static
binary carries everything it needs, so it runs there unchanged.
"""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

cmd = ["docker", "run", "--rm", "-v", "{}:/src".format(ROOT / "mapreduce"), "-w", "/src", "alpine:3.20", "sh", "-c",
       "apk add --no-cache g++ >/dev/null && mkdir -p bin"
       " && g++ -O2 -static -std=c++17 -o bin/mapper mapper.cpp"
       " && g++ -O2 -static -std=c++17 -o bin/reducer reducer.cpp"
       " && ls -la bin"]
subprocess.run(cmd, check=True)
