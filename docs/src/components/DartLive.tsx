import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import styles from './RustLive.module.css';
import LiveCodeEditor from './LiveCodeEditor';

interface DartLiveProps {
  code: string;

  /** Contents of the `file=…` include, prepended to the demo on every run. */
  hiddenCode?: string;

  /** Basename of that include, shown as the base tab's tooltip. */
  hiddenFile?: string;
}

interface CompileResponse {
  result?: unknown;
}

const DART_COMPILE_API =
  'https://stable.api.dartpad.dev/api/v3/compileNewDDC';

const DART_ARTIFACTS_BASE =
  'https://stable.api.dartpad.dev/artifacts/';

const DART_ENTRYPOINT =
  'package:dartpad_sample/bootstrap.dart';

const RUNNER_CHANNEL = 'dart-live-runner-v1';

const STARTUP_TIMEOUT_MS = 20_000;

/**
 * This contains no user-controlled source code.
 *
 * The compiled JS is sent later with postMessage(), rather than interpolated
 * into srcdoc. That avoids </script> / HTML injection problems.
 */
const DART_RUNNER_HTML = `
<!doctype html>
<html>
<head>
  <meta charset="utf-8">

  <script src="https://dartpad.dev/require.js"></script>

  <script>
    (() => {
      'use strict';

      const CHANNEL = '${RUNNER_CHANNEL}';
      const ARTIFACTS_BASE = '${DART_ARTIFACTS_BASE}';
      const ENTRYPOINT = '${DART_ENTRYPOINT}';

      let runtimeReady = false;
      let pendingCode = null;
      let hasExecuted = false;

      function stringifyError(value) {
        try {
          if (value && typeof value === 'object') {
            if (value.stack) {
              return String(value.stack);
            }

            if (value.message) {
              return String(value.message);
            }
          }

          return String(value);
        } catch (_) {
          return 'Unknown runtime error';
        }
      }

      function send(type, message) {
        parent.postMessage(
          {
            channel: CHANNEL,
            type,
            message:
              message === undefined
                ? undefined
                : String(message),
          },
          '*'
        );
      }

      // Dart print() uses this hook.
      self.dartPrint = function(message) {
        send('stdout', message);
      };

      // Keep normal console.error behavior but also send it to the parent.
      // DDC can report uncaught Dart exceptions this way.
      const originalConsoleError =
        console.error.bind(console);

      console.error = function(...args) {
        const message = args
          .map(stringifyError)
          .join(' ');

        send('stderr', message);
        originalConsoleError(...args);
      };

      self.addEventListener('error', function(event) {
        send(
          'stderr',
          stringifyError(
            event.error || event.message || 'Unknown runtime error'
          )
        );
      });

      self.addEventListener(
        'unhandledrejection',
        function(event) {
          send(
            'stderr',
            stringifyError(event.reason)
          );
        }
      );

      function execute(code) {
        if (hasExecuted) {
          return;
        }

        hasExecuted = true;

        try {
          /*
           * compileNewDDC returns code that registers DDC libraries with
           * dartDevEmbedder. The module loader and SDK must already exist
           * before this script executes.
           */
          const compiledScript =
            document.createElement('script');

          compiledScript.type = 'text/javascript';

          // textContent is intentional: the compiled source is not parsed
          // as HTML.
          compiledScript.textContent =
            code +
            '\\n//# sourceURL=dartlive-compiled.js';

          document.head.appendChild(compiledScript);

          if (
            !self.dartDevEmbedder ||
            typeof self.dartDevEmbedder.runMain !== 'function'
          ) {
            throw new Error(
              'Dart DDC runtime loaded, but dartDevEmbedder.runMain() is unavailable.'
            );
          }

          send('started');

          self.dartDevEmbedder.runMain(
            ENTRYPOINT,
            {}
          );

          /*
           * runMain() itself is synchronous. Dart async work may continue
           * after this message, so the iframe intentionally stays alive.
           */
          send('finished-sync');
        } catch (error) {
          send('stderr', stringifyError(error));
          send('finished-sync');
        }
      }

      self.addEventListener(
        'message',
        function(event) {
          if (event.source !== parent) {
            return;
          }

          const data = event.data;

          if (
            !data ||
            data.channel !== CHANNEL ||
            data.type !== 'run' ||
            typeof data.code !== 'string'
          ) {
            return;
          }

          if (runtimeReady) {
            execute(data.code);
          } else {
            pendingCode = data.code;
          }
        }
      );

      function runtimeFailure(error) {
        send(
          'fatal',
          'Failed to initialize Dart runtime: ' +
            stringifyError(error)
        );
      }

      try {
        require.config({
          baseUrl: ARTIFACTS_BASE,
          waitSeconds: 15,
        });

        /*
         * Ordering matters.
         *
         * dart_sdk_new expects dartDevEmbedder, which is established by
         * ddc_module_loader.
         */
        require(
          ['ddc_module_loader'],
          function() {
            require(
              ['dart_sdk_new'],
              function() {
                runtimeReady = true;
                send('ready');

                if (pendingCode !== null) {
                  const code = pendingCode;
                  pendingCode = null;
                  execute(code);
                }
              },
              runtimeFailure
            );
          },
          runtimeFailure
        );
      } catch (error) {
        runtimeFailure(error);
      }
    })();
  </script>
</head>

<body></body>
</html>
`;

function splitCode(source: string) {
  const lines = source.split('\n');

  let startIdx = 0;
  let endIdx = lines.length;

  /*
   * Preserve the same convention as RustLive:
   *
   * # hidden line
   *
   * at the beginning/end of an example.
   */
  while (
    startIdx < lines.length &&
    lines[startIdx].trimStart().startsWith('# ')
  ) {
    startIdx++;
  }

  while (
    endIdx > startIdx &&
    lines[endIdx - 1].trimStart().startsWith('# ')
  ) {
    endIdx--;
  }

  const headerLines = lines
    .slice(0, startIdx)
    .map((line) =>
      line.replace(/^(\s*)# /, '$1')
    );

  const footerLines = lines
    .slice(endIdx)
    .map((line) =>
      line.replace(/^(\s*)# /, '$1')
    );

  return {
    header:
      headerLines.length > 0
        ? `${headerLines.join('\n')}\n`
        : '',

    body: lines
      .slice(startIdx, endIdx)
      .join('\n'),

    footer:
      footerLines.length > 0
        ? `\n${footerLines.join('\n')}`
        : '',
  };
}

export default function DartLive({
  code: initialCode,
  hiddenCode,
  hiddenFile,
}: DartLiveProps) {
  const parsedCode = useMemo(
    () => splitCode(initialCode),
    [initialCode]
  );

  const [code, setCode] =
    useState(parsedCode.body);

  /*
   * The include is editable too, so it lives in state rather than being read
   * straight off the prop at run time.
   */
  const [includedCode, setIncludedCode] =
    useState(hiddenCode ?? '');

  const hasIncludedTab =
    (hiddenCode ?? '').trim().length > 0;

  const [output, setOutput] =
    useState<string | null>(null);

  const [isError, setIsError] =
    useState(false);

  const [running, setRunning] =
    useState(false);

  const iframeRef =
    useRef<HTMLIFrameElement | null>(null);

  const abortControllerRef =
    useRef<AbortController | null>(null);

  const messageListenerRef =
    useRef<((event: MessageEvent) => void) | null>(
      null
    );

  const startupTimeoutRef =
    useRef<ReturnType<typeof setTimeout> | null>(
      null
    );

  const activeRunRef =
    useRef(0);

  /*
   * Reset editor if Docusaurus reuses the component with a different
   * code prop during navigation.
   */
  useEffect(() => {
    setCode(parsedCode.body);
  }, [parsedCode.body]);

  useEffect(() => {
    setIncludedCode(hiddenCode ?? '');
  }, [hiddenCode]);

  const clearStartupTimeout =
    useCallback(() => {
      if (startupTimeoutRef.current) {
        clearTimeout(startupTimeoutRef.current);
        startupTimeoutRef.current = null;
      }
    }, []);

  const cleanupRunner =
    useCallback(() => {
      clearStartupTimeout();

      abortControllerRef.current?.abort();
      abortControllerRef.current = null;

      if (messageListenerRef.current) {
        window.removeEventListener(
          'message',
          messageListenerRef.current
        );

        messageListenerRef.current = null;
      }

      if (iframeRef.current) {
        iframeRef.current.remove();
        iframeRef.current = null;
      }
    }, [clearStartupTimeout]);

  useEffect(() => {
    return () => {
      activeRunRef.current++;
      cleanupRunner();
    };
  }, [cleanupRunner]);

  const runCode = useCallback(async () => {
    const runNumber =
      activeRunRef.current + 1;

    activeRunRef.current = runNumber;

    cleanupRunner();

    setRunning(true);
    setOutput(null);
    setIsError(false);

    const abortController =
      new AbortController();

    abortControllerRef.current =
      abortController;

    const hiddenPrefix = includedCode
      ? includedCode +
        (includedCode.endsWith('\n') ? '' : '\n')
      : '';

    const fullSource =
      hiddenPrefix +
      parsedCode.header +
      code +
      parsedCode.footer;

    try {
      /*
       * 1. Compile Dart using the current DartPad DDC backend.
       */
      const response = await fetch(
        DART_COMPILE_API,
        {
          method: 'POST',

          headers: {
            'Content-Type': 'application/json',
            Accept: 'application/json, text/plain',
          },

          body: JSON.stringify({
            source: fullSource,
          }),

          signal: abortController.signal,
        }
      );

      if (
        activeRunRef.current !== runNumber
      ) {
        return;
      }

      /*
       * compileNewDDC returns compiler failures as non-2xx text.
       * Do not blindly call response.json() here.
       */
      if (!response.ok) {
        const diagnostic =
          (await response.text()).trim();

        throw new Error(
          diagnostic ||
            `Dart compiler returned HTTP ${response.status}.`
        );
      }

      let data: CompileResponse;

      try {
        data =
          (await response.json()) as CompileResponse;
      } catch {
        throw new Error(
          'Dart compiler returned an invalid success response.'
        );
      }

      if (
        typeof data.result !== 'string' ||
        data.result.length === 0
      ) {
        throw new Error(
          'Dart compiler returned no compiled JavaScript.'
        );
      }

      const compiledJs = data.result;

      /*
       * 2. Create an isolated runner.
       *
       * Deliberately DO NOT use allow-same-origin.
       * User Dart code therefore executes with an opaque origin and cannot
       * directly inspect the parent Docusaurus page.
       */
      const iframe =
        document.createElement('iframe');

      iframe.setAttribute(
        'sandbox',
        'allow-scripts'
      );

      iframe.setAttribute(
        'aria-hidden',
        'true'
      );

      iframe.setAttribute(
        'title',
        'Dart code execution sandbox'
      );

      iframe.style.display = 'none';

      iframe.srcdoc = DART_RUNNER_HTML;

      iframeRef.current = iframe;

      const capturedLines: string[] = [];

      const appendOutput = (
        message: unknown
      ) => {
        const text = String(message ?? '');

        if (!text) {
          return;
        }

        /*
         * Avoid the most common duplicate error case where both
         * console.error and window.onerror report the exact same line.
         */
        if (
          capturedLines[
            capturedLines.length - 1
          ] !== text
        ) {
          capturedLines.push(text);
        }

        setOutput(
          capturedLines.join('\n')
        );
      };

      const stopSpinner = () => {
        clearStartupTimeout();

        if (
          activeRunRef.current ===
          runNumber
        ) {
          setRunning(false);
        }
      };

      const messageHandler = (
        event: MessageEvent
      ) => {
        if (
          event.source !==
          iframe.contentWindow
        ) {
          return;
        }

        const data = event.data;

        if (
          !data ||
          data.channel !== RUNNER_CHANNEL
        ) {
          return;
        }

        switch (data.type) {
          case 'ready': {
            iframe.contentWindow?.postMessage(
              {
                channel: RUNNER_CHANNEL,
                type: 'run',
                code: compiledJs,
              },
              '*'
            );

            break;
          }

          case 'started': {
            /*
             * Compilation + runtime loading are complete.
             * Async Dart code can continue emitting output afterward.
             */
            stopSpinner();
            break;
          }

          case 'stdout': {
            appendOutput(data.message);
            break;
          }

          case 'stderr': {
            setIsError(true);
            appendOutput(data.message);
            stopSpinner();
            break;
          }

          case 'finished-sync': {
            stopSpinner();

            if (
              capturedLines.length === 0
            ) {
              setOutput('(no output)');
            }

            break;
          }

          case 'fatal': {
            setIsError(true);

            appendOutput(
              data.message ||
                'Failed to initialize Dart runtime.'
            );

            stopSpinner();

            /*
             * No asynchronous Dart work can be running if runtime
             * initialization itself failed.
             */
            iframe.remove();

            if (
              iframeRef.current === iframe
            ) {
              iframeRef.current = null;
            }

            break;
          }

          default:
            break;
        }
      };

      messageListenerRef.current =
        messageHandler;

      window.addEventListener(
        'message',
        messageHandler
      );

      document.body.appendChild(iframe);

      /*
       * Only protects startup/module loading.
       *
       * We cannot safely terminate arbitrary synchronous JS once main()
       * is already executing in an iframe.
       */
      startupTimeoutRef.current =
        setTimeout(() => {
          if (
            activeRunRef.current !==
            runNumber
          ) {
            return;
          }

          setRunning(false);
          setIsError(true);

          setOutput(
            'Timed out while loading the Dart execution runtime.'
          );

          if (iframeRef.current === iframe) {
            iframe.remove();
            iframeRef.current = null;
          }
        }, STARTUP_TIMEOUT_MS);
    } catch (error: unknown) {
      if (
        activeRunRef.current !== runNumber
      ) {
        return;
      }

      if (
        error instanceof DOMException &&
        error.name === 'AbortError'
      ) {
        return;
      }

      setRunning(false);
      setIsError(true);

      setOutput(
        error instanceof Error
          ? error.message
          : 'Unknown Dart execution error.'
      );
    }
  }, [
    cleanupRunner,
    clearStartupTimeout,
    code,
    includedCode,
    parsedCode.header,
    parsedCode.footer,
  ]);

  return (
    <div className={styles.container}>
      <div className={styles.toolbar}>
        <div className={styles.toolbarLeft}>
          <span className={styles.langBadge}>
            Dart
          </span>
        </div>

        <button
          className={styles.runButton}
          onClick={runCode}
          disabled={running}
          title="Run (Ctrl+Enter)"
        >
          {running ? (
            <>
              <span
                className={styles.spinner}
              />{' '}
              Running
            </>
          ) : (
            '▶ Run'
          )}
        </button>
      </div>

      <LiveCodeEditor
        language="dart"
        languageLabel="Dart"
        demo={code}
        onDemoChange={setCode}
        base={includedCode}
        onBaseChange={setIncludedCode}
        hasBase={hasIncludedTab}
        baseFile={hiddenFile}
        indent="  "
        onRun={runCode}
      />

      {output !== null && (
        <div className={styles.output}>
          <div
            className={styles.outputHeader}
          >
            <span
              className={styles.outputLabel}
            >
              Output
            </span>

            <button
              className={
                styles.clearButton
              }
              onClick={() =>
                setOutput(null)
              }
            >
              Clear
            </button>
          </div>

          <div
            className={`${styles.outputContent} ${
              isError
                ? styles.outputError
                : ''
            }`}
          >
            {output}
          </div>
        </div>
      )}
    </div>
  );
}
