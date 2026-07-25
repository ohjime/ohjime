import React, {
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';
import { Highlight, themes } from 'prism-react-renderer';
import { useColorMode } from '@docusaurus/theme-common';
import styles from './RustLive.module.css';

/**
 * The editing surface shared by RustLive, DartLive and FlutterLive.
 *
 * Two tabs at most, both editable:
 *
 *   demo — the code block written in the markdown, and what the reader is
 *          meant to play with. Always present, always the tab you land on.
 *   base — the contents of the `file=…` include, prepended to demo on every
 *          run. Only shown when the block actually includes a file.
 *
 * The caller owns both strings, because both are needed to assemble the
 * source at run time.
 */
interface LiveCodeEditorProps {
  /** Prism language id, e.g. 'rust' or 'dart'. */
  language: string;

  demo: string;
  onDemoChange: (value: string) => void;

  base: string;
  onBaseChange: (value: string) => void;

  /** Whether this block includes a file at all. */
  hasBase: boolean;

  /** Real filename of the include, shown as the base tab's tooltip. */
  baseFile?: string;

  /** What one Tab press inserts. */
  indent: string;

  /** Ctrl/Cmd + Enter. */
  onRun: () => void;

  /** Human-readable language name, for the editor's accessible name. */
  languageLabel: string;
}

type Tab = 'demo' | 'base';

export default function LiveCodeEditor({
  language,
  demo,
  onDemoChange,
  base,
  onBaseChange,
  hasBase,
  baseFile,
  indent,
  onRun,
  languageLabel,
}: LiveCodeEditorProps) {
  const [activeTab, setActiveTab] =
    useState<Tab>('demo');

  const textareaRef =
    useRef<HTMLTextAreaElement>(null);

  const { colorMode } = useColorMode();

  useEffect(() => {
    if (!hasBase) {
      setActiveTab('demo');
    }
  }, [hasBase]);

  const value =
    activeTab === 'demo' ? demo : base;

  const onChange =
    activeTab === 'demo'
      ? onDemoChange
      : onBaseChange;

  const handleKeyDown = useCallback(
    (
      event: React.KeyboardEvent<HTMLTextAreaElement>
    ) => {
      if (
        event.key === 'Enter' &&
        (event.metaKey || event.ctrlKey)
      ) {
        event.preventDefault();
        onRun();
        return;
      }

      if (event.key === 'Tab') {
        event.preventDefault();

        const textarea = event.currentTarget;
        const start = textarea.selectionStart;
        const end = textarea.selectionEnd;

        onChange(
          value.substring(0, start) +
            indent +
            value.substring(end)
        );

        // Restore the caret after React re-renders.
        requestAnimationFrame(() => {
          textarea.selectionStart =
            textarea.selectionEnd =
              start + indent.length;
        });
      }
    },
    [indent, onChange, onRun, value]
  );

  const theme =
    colorMode === 'dark'
      ? themes.vsDark
      : themes.vsLight;

  const tabClass = (tab: Tab) =>
    `${styles.tab} ${
      activeTab === tab ? styles.tabActive : ''
    }`;

  return (
    <>
      {hasBase && (
        <div
          className={styles.tabBar}
          role="tablist"
          aria-label="Source"
        >
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === 'demo'}
            className={tabClass('demo')}
            onClick={() => setActiveTab('demo')}
            title="The example from this page"
          >
            demo
          </button>

          <button
            type="button"
            role="tab"
            aria-selected={activeTab === 'base'}
            className={tabClass('base')}
            onClick={() => setActiveTab('base')}
            title={
              baseFile
                ? `Included from ${baseFile}, prepended to demo on every run`
                : 'Prepended to demo on every run'
            }
          >
            base
          </button>
        </div>
      )}

      <div className={styles.editorScroll}>
        <div className={styles.editorWrapper}>
          <Highlight
            theme={theme}
            code={value}
            language={language as any}
          >
            {({
              className,
              style,
              tokens,
              getLineProps,
              getTokenProps,
            }) => (
              <pre
                className={`${className} ${styles.pre}`}
                style={{
                  ...style,
                  background: 'transparent',
                }}
              >
                {tokens.map((line, i) => (
                  <div
                    key={i}
                    {...getLineProps({ line })}
                  >
                    {line.map((token, key) => (
                      <span
                        key={key}
                        {...getTokenProps({
                          token,
                        })}
                      />
                    ))}
                  </div>
                ))}
              </pre>
            )}
          </Highlight>

          <textarea
            ref={textareaRef}
            className={styles.textarea}
            value={value}
            onChange={(event) =>
              onChange(event.target.value)
            }
            onKeyDown={handleKeyDown}
            spellCheck={false}
            autoCapitalize="off"
            autoCorrect="off"
            wrap="off"
            aria-label={
              activeTab === 'demo'
                ? `${languageLabel} code editor`
                : `${languageLabel} base editor`
            }
          />
        </div>
      </div>
    </>
  );
}
