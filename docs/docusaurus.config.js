// @ts-check
// Note: type annotations allow type checking and IDEs autocompletion

const lightCodeTheme = require('prism-react-renderer').themes.vsLight;
const darkCodeTheme = require('prism-react-renderer').themes.vsDark;
const tailwindPlugin = require('./src/plugins/tailwind-config.cjs');
const rustLivePlugin = require('./src/remark/rust-live');

/** @type {() => Promise<import('@docusaurus/types').Config>} */
module.exports = async function createConfigAsync() {
  // KaTeX plugins (ESM-only, require dynamic import)
  const remarkMath = (await import('remark-math')).default;
  const rehypeKatex = (await import('rehype-katex')).default;

  return {
    title: "Ozzy's Korner",
    tagline: "Ozzy's Korner",
    url: 'https://ohji.me',
    baseUrl: '/',
    organizationName: 'ohjime',
    projectName: 'portfolio',
    deploymentBranch: 'gh-pages',
    trailingSlash: false,
    onBrokenLinks: 'throw',
    onBrokenMarkdownLinks: 'warn',
    favicon: 'images/icons/favicon.png',

    i18n: {
      defaultLocale: 'en',
      locales: ['en'],
    },

    markdown: {
      mermaid: true,
      format: 'detect',
    },

    themes: ['@docusaurus/theme-mermaid'],

    plugins: [
      tailwindPlugin,
      ['docusaurus-plugin-sass', {}],
      ['@docusaurus/plugin-ideal-image', {
        quality: 90,
        max: 2560,
        min: 256,
        steps: 6,
        disableInDev: false,
      }],
      // Main blog plugin
      [
        '@docusaurus/plugin-content-blog',
        {
          id: 'posts',
          routeBasePath: '/posts/',
          path: 'posts',
          showReadingTime: true,
          editUrl: 'https://github.com/ohjime/portfolio/tree/main/docs/',
          remarkPlugins: [remarkMath, rustLivePlugin],
          rehypePlugins: [rehypeKatex],
        },
      ],
      // Things blog plugin
      [
        '@docusaurus/plugin-content-blog',
        {
          id: 'things',
          routeBasePath: '/things/',
          path: 'things',
          showReadingTime: false,
          editUrl: 'https://github.com/ohjime/portfolio/tree/main/docs/',
          blogTitle: 'Things',
          blogDescription: 'A collection of random things on many things.',
          postsPerPage: 'ALL',
          blogSidebarCount: 0,
          sortPosts: 'ascending',
          processBlogPosts: async ({ blogPosts }) => {
            return blogPosts.sort((a, b) => {
              const filenameA = a.metadata.source.split('/').pop() || ''
              const filenameB = b.metadata.source.split('/').pop() || ''
              return filenameA.localeCompare(filenameB)
            })
          },
          feedOptions: {
            type: 'all',
            title: "Ozzy's Korner - Things",
            description: 'A Collection of Random Things I Made or Seen',
            limit: false,
          },
          blogListComponent: '@site/src/theme/concepts/BlogListPage',
          blogPostComponent: '@site/src/theme/concepts/BlogPostPage',
          remarkPlugins: [remarkMath, rustLivePlugin],
          rehypePlugins: [rehypeKatex],
        },
      ],
    ],

    presets: [
      [
        '@docusaurus/preset-classic',
        /** @type {import('@docusaurus/preset-classic').Options} */
        ({
          docs: {
            path: 'notes',
            routeBasePath: '/notes/',
            sidebarPath: require.resolve('./sidebars.js'),
            editUrl: 'https://github.com/ohjime/portfolio/tree/main/docs/',
            breadcrumbs: true,
            admonitions: true,
            showLastUpdateTime: true,
            remarkPlugins: [remarkMath, rustLivePlugin],
            rehypePlugins: [rehypeKatex],
          },
          blog: false, // Disabled because we're using separate blog plugins
          theme: {
            customCss: require.resolve('./src/css/global.css'),
          },
        }),
      ],
    ],

    stylesheets: [
      {
        href: "https://cdn.jsdelivr.net/npm/katex@0.16.28/dist/katex.min.css",
        integrity: "sha384-Wsr4Nh3yrvMf2KCebJchRJoVo1gTU6kcP05uRSh5NV3sj9+a8IomuJoQzf3sMq4T",
        crossorigin: "anonymous",
      },
    ],

    themeConfig:
      /** @type {import('@docusaurus/preset-classic').ThemeConfig} */
      ({
        docs: {
          sidebar: {
            autoCollapseCategories: true,
          },
        },
        navbar: {
          title: "Ozzy's Korner",
          items: [
            {
              type: 'doc',
              docId: 'index',
              position: 'left',
              label: 'Notes',
            },
            { to: '/posts', label: 'Posts', position: 'left' },
            { to: '/things', label: 'Things', position: 'left' },
            {
              href: 'https://github.com/ohjime/',
              position: 'right',
              className: 'navbar-github-icon',
              'aria-label': 'GitHub repository',
            },
          ],
        },
        footer: {
          links: [
            {
              title: 'About',
              items: [
                {
                  to: '/',
                  label: 'Projects',
                },
                {
                  to: '/notes/',
                  label: 'Notes',
                },
                {
                  label: 'Posts',
                  to: '/posts/',
                },
                {
                  label: 'Things',
                  to: '/things',
                },
                {
                  label: 'Tools',
                  to: '/',
                },
              ],
            },
            {
              title: 'More',
              items: [
                {
                  label: 'GitHub',
                  href: 'https://github.com/ohjime/',
                },
              ],
            },
          ],
        },
        prism: {
          additionalLanguages: ['bash', 'dart', 'yaml'],
          theme: lightCodeTheme,
          darkTheme: darkCodeTheme,
        },
        mermaid: {
          theme: {
            light: 'neutral',
            dark: 'forest',
          },
        },
      }),
  };
};
