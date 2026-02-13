const { visit } = require('unist-util-visit');

const fs = require('fs');
const path = require('path');

const plugin = (options) => {
  const transformer = (ast, vfile) => {
    visit(ast, 'code', (node) => {
      // Check if the code block is 'rust' and has the 'live' meta tag
      // Meta can be complex like 'live file=./foo.rs'
      if (node.lang === 'rust' && (node.meta === 'live' || (node.meta && node.meta.startsWith('live ')))) {
        let hiddenCode = '';

        // Parse 'file=...' attribute from meta string
        const fileMatch = node.meta.match(/file=(["']?)([^"'\s]+)\1/);
        if (fileMatch) {
          const relativePath = fileMatch[2];
          // vfile.history[0] is the absolute path of the markdown file being processed
          const markdownDir = path.dirname(vfile.history[0]);
          const absolutePath = path.resolve(markdownDir, relativePath);

          try {
            hiddenCode = fs.readFileSync(absolutePath, 'utf8');
          } catch (err) {
            console.error(`[RustLive] Failed to read file: ${absolutePath}`, err);
          }
        }

        // Transform into an mdxJsxFlowElement (MDX v3 / Docusaurus v3)
        node.type = 'mdxJsxFlowElement';
        node.name = 'RustLive';
        node.attributes = [
          {
            type: 'mdxJsxAttribute',
            name: 'code',
            value: node.value,
          },
          {
            type: 'mdxJsxAttribute',
            name: 'hiddenCode',
            value: hiddenCode,
          },
        ];
        node.children = [];
        node.data = undefined;
      }
    });
  };
  return transformer;
};

module.exports = plugin;
