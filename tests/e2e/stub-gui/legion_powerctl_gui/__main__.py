# SPDX-License-Identifier: MIT

import json
import os
import sys

print(json.dumps({"cwd": os.getcwd(), "env": dict(os.environ), "sys_path": sys.path,
                  "argv": sys.argv}))
