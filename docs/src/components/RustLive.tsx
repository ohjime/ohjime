import React, { useState, useRef, useCallback, useEffect } from 'react';
import { Highlight, themes } from 'prism-react-renderer';
import { useColorMode } from '@docusaurus/theme-common';
import styles from './RustLive.module.css';

interface RustLiveProps {
  code: string;
  hiddenCode?: string;
}

const API_URL = 'https://play.rust-lang.org/execute';

export default function RustLive({ code: initialCode, hiddenCode }: RustLiveProps) {
  // Parse existing code to find hidden lines at start (header) and end (footer)
  // Pattern: lines starting with "# " are hidden.
  // We only support hidden lines at the top and bottom to avoid complex interleaving logic during edits.
  const [header, setHeader] = useState('');
  const [footer, setFooter] = useState('');
  const [code, setCode] = useState(() => {
    const lines = initialCode.split('\n');
    let startIdx = 0;
    let endIdx = lines.length;

    // Extract header
    while (startIdx < lines.length && lines[startIdx].trimStart().startsWith('# ')) {
      startIdx++;
    }

    // Extract footer
    while (endIdx > startIdx && lines[endIdx - 1].trimStart().startsWith('# ')) {
      endIdx--;
    }

    const headerLines = lines.slice(0, startIdx).map(line => line.replace(/^(\s*)# /, '$1'));
    const footerLines = lines.slice(endIdx).map(line => line.replace(/^(\s*)# /, '$1'));
    const bodyLines = lines.slice(startIdx, endIdx);

    setHeader(headerLines.join('\n') + (headerLines.length ? '\n' : ''));
    setFooter((footerLines.length ? '\n' : '') + footerLines.join('\n'));

    return bodyLines.join('\n');
  });
  const [edition, setEdition] = useState<'2021' | '2024'>('2021');
  const [output, setOutput] = useState<string | null>(null);
  const [isError, setIsError] = useState(false);
  const [running, setRunning] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const preRef = useRef<HTMLPreElement>(null);
  const { colorMode } = useColorMode();

  // Sync textarea scroll with the highlighted pre
  const handleScroll = useCallback(() => {
    if (textareaRef.current && preRef.current) {
      preRef.current.scrollTop = textareaRef.current.scrollTop;
      preRef.current.scrollLeft = textareaRef.current.scrollLeft;
    }
  }, []);

  // Auto-resize textarea height to match content
  useEffect(() => {
    const ta = textareaRef.current;
    if (ta) {
      ta.style.height = 'auto';
      ta.style.height = `${ta.scrollHeight}px`;
    }
  }, [code]);

  const runCode = useCallback(async () => {
    setRunning(true);
    setOutput(null);
    setIsError(false);

    try {
      const response = await fetch(API_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          code: (hiddenCode ? hiddenCode + '\n' : '') + header + code + footer,
          channel: 'stable',
          mode: 'debug',
          edition,
          crateType: 'bin',
          tests: false,
          backtrace: false,
        }),
      });

      if (!response.ok) {
        throw new Error(`Server responded with ${response.status}`);
      }

      const data = await response.json();
      if (!data.success) {
        setIsError(true);
        setOutput(data.stderr || '(compilation failed)');
      } else {
        setOutput(data.stdout || '(no output)');
      }
    } catch (err: unknown) {
      setIsError(true);
      setOutput(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setRunning(false);
    }
  }, [code, edition]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      // Ctrl/Cmd + Enter to run
      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        runCode();
        return;
      }
      // Tab inserts 4 spaces
      if (e.key === 'Tab') {
        e.preventDefault();
        const ta = e.currentTarget;
        const start = ta.selectionStart;
        const end = ta.selectionEnd;
        const spaces = '    ';
        setCode((prev) => prev.substring(0, start) + spaces + prev.substring(end));
        // Restore cursor position after React re-render
        requestAnimationFrame(() => {
          ta.selectionStart = ta.selectionEnd = start + spaces.length;
        });
      }
    },
    [runCode],
  );

  const theme = colorMode === 'dark' ? themes.vsDark : themes.vsLight;

  return (
    <div className={styles.container}>
      {/* ── Toolbar ── */}
      <div className={styles.toolbar}>
        <div className={styles.toolbarLeft}>
          <span className={styles.langBadge}>Rust</span>
          <select
            className={styles.editionSelect}
            value={edition}
            onChange={(e) => setEdition(e.target.value as '2021' | '2024')}
            aria-label="Rust edition"
          >
            <option value="2021">2021</option>
            <option value="2024">2024</option>
          </select>
        </div>
        <button
          className={styles.runButton}
          onClick={runCode}
          disabled={running}
          title="Run (Ctrl+Enter)"
        >
          {running ? (
            <>
              <span className={styles.spinner} /> Running…
            </>
          ) : (
            '▶ Run'
          )}
        </button>
      </div>

      {/* ── Editor ── */}
      <div className={styles.editorWrapper}>
        <Highlight theme={theme} code={code} language="rust">
          {({ className, style, tokens, getLineProps, getTokenProps }) => (
            <pre ref={preRef} className={`${className} ${styles.pre}`} style={{ ...style, background: 'transparent' }}>
              {tokens.map((line, i) => (
                <div key={i} {...getLineProps({ line })}>
                  {line.map((token, key) => (
                    <span key={key} {...getTokenProps({ token })} />
                  ))}
                </div>
              ))}
            </pre>
          )}
        </Highlight>
        <textarea
          ref={textareaRef}
          className={styles.textarea}
          value={code}
          onChange={(e) => setCode(e.target.value)}
          onScroll={handleScroll}
          onKeyDown={handleKeyDown}
          spellCheck={false}
          autoCapitalize="off"
          autoCorrect="off"
          aria-label="Rust code editor"
        />
      </div>

      {/* ── Output ── */}
      {output !== null && (
        <div className={styles.output}>
          <div className={styles.outputHeader}>
            <span className={styles.outputLabel}>Output</span>
            <button className={styles.clearButton} onClick={() => setOutput(null)}>
              Clear
            </button>
          </div>
          <div className={`${styles.outputContent} ${isError ? styles.outputError : ''}`}>
            {output}
          </div>
        </div>
      )}
    </div>
  );
}
