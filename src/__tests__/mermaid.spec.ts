import { renderMermaidInTheme } from '../index';

// Jest cannot load these JupyterLab packages, and the function under test
// uses none of them at run time
jest.mock('@jupyterlab/application', () => ({}));
jest.mock('@jupyterlab/apputils', () => ({}));
jest.mock('@jupyterlab/mainmenu', () => ({}));
jest.mock('@jupyterlab/mermaid', () => ({}));

/** A mermaid whose site config is what JupyterLab's manager applied. */
function fakeMermaid(render: () => Promise<{ svg: string }>) {
  const calls: any[] = [];
  const site = {
    theme: 'dark',
    fontFamily: 'jp-font',
    securityLevel: 'strict',
    maxTextSize: 100000,
    maxEdges: 100000,
    startOnLoad: false,
    layout: 'dagre'
  };
  const mermaid = {
    mermaidAPI: { getSiteConfig: () => ({ ...site }) },
    initialize: (config: any) => calls.push(config),
    render
  };
  const manager: any = { getMermaid: async () => mermaid };
  const { layout, ...jupyterlabOptions } = site;
  return { manager, calls, jupyterlabOptions };
}

describe('renderMermaidInTheme', () => {
  it('gives the shared mermaid its JupyterLab options back', async () => {
    const ok = fakeMermaid(async () => ({ svg: '<svg/>' }));
    expect(
      await renderMermaidInTheme(ok.manager, 'graph TD; a-->b', 'light')
    ).toBe('<svg/>');
    expect(ok.calls[0]).toMatchObject({
      theme: 'default',
      securityLevel: 'loose'
    });
    // the six options only: a whole site config would carry `layout`
    expect(ok.calls[1]).toEqual(ok.jupyterlabOptions);

    const failing = fakeMermaid(async () => {
      throw new Error('syntax');
    });
    jest.spyOn(console, 'warn').mockImplementation(() => undefined);
    expect(await renderMermaidInTheme(failing.manager, 'x', 'dark')).toBe(null);
    expect(failing.calls[1]).toEqual(failing.jupyterlabOptions);
  });
});
