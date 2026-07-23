/**
 * Copy the mermaid bundle the browser uses into the Python package.
 *
 * The server renders mermaid for exports driven through the REST API, where
 * there is no browser to do it. Resolving through @jupyterlab/mermaid's own
 * tree rather than a top-level dependency keeps the vendored copy the same
 * mermaid JupyterLab renders with, so the two cannot drift apart.
 */
const fs = require('fs');
const path = require('path');

const OUT_DIR = path.join(
  __dirname,
  '..',
  'jupyterlab_export_markdown_extension',
  'vendor'
);

function resolveBundle() {
  try {
    const jupyterlabMermaid =
      require.resolve('@jupyterlab/mermaid/package.json');
    return require.resolve('mermaid/dist/mermaid.min.js', {
      paths: [path.dirname(jupyterlabMermaid)]
    });
  } catch (error) {
    console.error(
      'vendor:mermaid - could not find mermaid/dist/mermaid.min.js through ' +
        '@jupyterlab/mermaid. Run `jlpm install` first; if mermaid has ' +
        'stopped shipping a UMD build, the server-side renderer needs one.\n' +
        error.message
    );
    process.exit(1);
  }
}

const source = resolveBundle();
fs.mkdirSync(OUT_DIR, { recursive: true });
fs.copyFileSync(source, path.join(OUT_DIR, 'mermaid.min.js'));
