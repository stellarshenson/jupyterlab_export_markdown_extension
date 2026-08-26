"""Server configuration for integration tests.

!! Never use this configuration in production because it
opens the server to the world and provide access to JupyterLab
JavaScript objects through the global window variable.
"""
import os

from jupyterlab.galata import configure_jupyter_server

configure_jupyter_server(c)

# Only when asked: configure_jupyter_server has already set 8888, so writing a
# default here would put the same number in two languages with nothing tying
# them. Read with `or`, not a get() default - an exported-but-empty value would
# raise ValueError here while Playwright waited happily on the old port.
if os.environ.get("JUPYTER_TEST_PORT"):
    c.ServerApp.port = int(os.environ["JUPYTER_TEST_PORT"])

# Uncomment to set server log level to debug level
# c.ServerApp.log_level = "DEBUG"
