/**
 * Configuration for Playwright using default from @jupyterlab/galata
 */
const baseConfig = require('@jupyterlab/galata/lib/playwright-config');

// Galata's server config pins the port and sets `port_retries = 0`, so the test
// server dies rather than move when the port is taken - a developer running
// their own lab on 8888 cannot run the suite at all. One variable feeds both
// ends: this config and `jupyter_server_test_config.py`.
const PORT = process.env.JUPYTER_TEST_PORT || '8888';
const BASE_URL = `http://localhost:${PORT}`;

module.exports = {
  ...baseConfig,
  // One Jupyter server serves every spec. Two Labs booting against it at once
  // make galata's readiness wait time out on this machine, so the specs run
  // one at a time - measured, not assumed.
  workers: 1,
  use: {
    ...baseConfig.use,
    // Galata resolves its own baseURL as use.baseURL -> TARGET_URL -> a
    // hardcoded 8888, and its base config sets none, so the port knob only
    // reaches the browser if it is set here.
    baseURL: BASE_URL
  },
  webServer: {
    command: 'jlpm start',
    url: `${BASE_URL}/lab`,
    timeout: 120 * 1000,
    // Never adopt a server this suite did not start - the tests create and
    // delete documents, and an adopted one could be someone's real lab.
    reuseExistingServer: false
  }
};
