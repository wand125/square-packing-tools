"""Measure one child without macOS time -l's sandbox-restricted sysctl call."""
import json
import resource
import subprocess
import sys

result = subprocess.run(sys.argv[1:])
usage = resource.getrusage(resource.RUSAGE_CHILDREN)
print(json.dumps(dict(peak_rss_bytes=usage.ru_maxrss * (1 if sys.platform == 'darwin' else 1024),
                      user_seconds=usage.ru_utime, system_seconds=usage.ru_stime)), file=sys.stderr)
sys.exit(result.returncode)
