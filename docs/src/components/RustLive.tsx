import React, { useState, useCallback, useEffect } from 'react';
import styles from './RustLive.module.css';
import LiveCodeEditor from './LiveCodeEditor';

interface RustLiveProps {
  code: string;

  /** Contents of the `file=…` include, prepended to the demo on every run. */
  hiddenCode?: string;

  /** Basename of that include, shown as the base tab's tooltip. */
  hiddenFile?: string;
}

const API_URL = 'https://play.rust-lang.org/execute';

export default function RustLive({
  code: initialCode,
  hiddenCode,
  hiddenFile,
}: RustLiveProps) {
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
  // The include is editable too, so it lives in state rather than being read
  // straight off the prop at run time.
  const [includedCode, setIncludedCode] = useState(hiddenCode ?? '');
  const hasIncludedTab = (hiddenCode ?? '').trim().length > 0;

  const [edition, setEdition] = useState<'2021' | '2024'>('2021');
  const [output, setOutput] = useState<string | null>(null);
  const [isError, setIsError] = useState(false);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    setIncludedCode(hiddenCode ?? '');
  }, [hiddenCode]);

  const runCode = useCallback(async () => {
    setRunning(true);
    setOutput(null);
    setIsError(false);

    try {
      const response = await fetch(API_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          code:
            (includedCode ? includedCode + '\n' : '') + header + code + footer,
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
  }, [code, includedCode, header, footer, edition]);

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
      <LiveCodeEditor
        language="rust"
        languageLabel="Rust"
        demo={code}
        onDemoChange={setCode}
        base={includedCode}
        onBaseChange={setIncludedCode}
        hasBase={hasIncludedTab}
        baseFile={hiddenFile}
        indent="    "
        onRun={runCode}
      />

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
