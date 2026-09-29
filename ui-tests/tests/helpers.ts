/**
 * Ready means the splash gone and the shell mounted. Galata's default also
 * waits for the Launcher tab to be active, and a lab whose extensions open a
 * tab of their own at startup (a message of the day) keeps the Launcher
 * inactive, so every test timed out inside `page.goto()`. No spec here uses
 * the Launcher.
 */
export const labFixtures = {
  waitForApplication: async ({ baseURL }: any, use: any) => {
    await use(async (page: any) => {
      await page.locator('#jupyterlab-splash').waitFor({ state: 'detached' });
      await page.locator('#main').waitFor();
    });
  }
};
