import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import styles from './RustLive.module.css';
import flutterStyles from './FlutterLive.module.css';
import LiveCodeEditor from './LiveCodeEditor';

interface FlutterLiveProps {
  code: string;

  /** Contents of the `file=…` include, prepended to the snippet on every run. */
  hiddenCode?: string;

  /** Basename of that include, shown as the base tab's tooltip. */
  hiddenFile?: string;
}

type View = 'code' | 'preview';

interface CompileResponse {
  result?: unknown;
  deltaDill?: unknown;
}

interface VersionResponse {
  dartVersion?: unknown;
  flutterVersion?: unknown;
  engineVersion?: unknown;
}

const DARTPAD_CHANNEL_URL =
  'https://stable.api.dartpad.dev/';

const COMPILE_API =
  `${DARTPAD_CHANNEL_URL}api/v3/compileNewDDC`;

const VERSION_API =
  `${DARTPAD_CHANNEL_URL}api/v3/version`;

const ARTIFACTS_BASE =
  `${DARTPAD_CHANNEL_URL}artifacts/`;

/*
 * DartPad's own frame.html lives at https://dartpad.dev/frame.html and passes
 * assetBase: 'frame/'. Our runner is an about:srcdoc document, whose base URL
 * is inherited from the parent page, so the same relative value would resolve
 * against this site. The absolute equivalent is required.
 */
const DARTPAD_ASSET_BASE =
  'https://dartpad.dev/frame/';

const FLUTTER_ENTRYPOINT =
  'package:dartpad_sample/bootstrap.dart';

const RUNNER_CHANNEL = 'flutter-live-runner-v1';

/*
 * dart_sdk_new.js and flutter_web_new.js are roughly 11 MB gzipped combined on
 * a cold cache, so the startup budget is deliberately generous. Errors short
 * circuit this via 'stderr'/'fatal' rather than waiting it out.
 */
const STARTUP_TIMEOUT_MS = 90_000;

/**
 * compileNewDDC output is not independently executable: it only registers DDC
 * libraries with dartDevEmbedder.
 *
 * This reproduces DartPad's own decoration for the "new DDC + Flutter" path:
 * point require.js at the artifacts host, load ddc_module_loader, then
 * dart_sdk_new + flutter_web_new, then run the compiler output and hand control
 * to the generated bootstrap.
 *
 * The block scope (rather than an IIFE) and the absence of 'use strict' are
 * deliberate: they match DartPad, and the DDC output is only known to run under
 * those conditions.
 */
function decorateFlutterJavaScript(compiledJs: string): string {
  return `
window.dartPrint = function (message) {
  window.__flutterLiveSend('stdout', message);
};

window.onerror = function (message, url, line, column, error) {
  window.__flutterLiveSend(
    'stderr',
    message + (error == null ? '' : ', error: ' + error)
  );
};

require.config({
  "baseUrl": ${JSON.stringify(ARTIFACTS_BASE)},
  "waitSeconds": 60,
  "onNodeCreated": function (node, config, id, url) {
    node.setAttribute('crossorigin', 'anonymous');
  }
});

{
  let __ddcInitCode = function () {${compiledJs}};

  function contextLoaded() {
    try {
      __ddcInitCode();

      if (
        !window.dartDevEmbedder ||
        typeof window.dartDevEmbedder.runMain !== 'function'
      ) {
        throw new Error(
          'Flutter DDC runtime loaded, but dartDevEmbedder.runMain() is unavailable.'
        );
      }

      window.__flutterLiveSend('status', 'Starting Flutter engine');

      /*
       * The generated bootstrap calls ui_web.bootstrapEngine(), which resolves
       * _flutter.loader's onEntrypointLoaded callback in the runner.
       */
      window.dartDevEmbedder.runMain(${JSON.stringify(
        FLUTTER_ENTRYPOINT,
      )}, {});
    } catch (error) {
      window.__flutterLiveSend('fatal', error);
    }
  }

  function moduleLoaderLoaded() {
    window.__flutterLiveSend('status', 'Loading Flutter SDK');

    require(
      ["dart_sdk_new", "flutter_web_new"],
      contextLoaded,
      function (error) {
        window.__flutterLiveSend(
          'fatal',
          'Failed to load the Flutter SDK modules: ' + error
        );
      }
    );
  }

  require(
    ["ddc_module_loader"],
    moduleLoaderLoaded,
    function (error) {
      window.__flutterLiveSend(
        'fatal',
        'Failed to load the DDC module loader: ' + error
      );
    }
  );
}
//# sourceURL=flutterlive-compiled.js
`;
}

/**
 * Contains no user-controlled source.
 *
 * Compiled output arrives later over postMessage rather than being
 * interpolated into srcdoc, which sidesteps </script> and HTML injection
 * problems entirely.
 */
const FLUTTER_RUNNER_HTML = `
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">

  <style>
    html, body {
      width: 100%;
      height: 100%;
      margin: 0;
      padding: 0;
      overflow: hidden;
      background: transparent;
    }

    flt-glass-pane, flutter-view {
      width: 100%;
      height: 100%;
    }
  </style>

  <script src="https://dartpad.dev/require.js"></script>
  <script src="https://dartpad.dev/flutter.js"></script>

  <script>
    (() => {
      const CHANNEL = ${JSON.stringify(RUNNER_CHANNEL)};
      const ASSET_BASE = ${JSON.stringify(DARTPAD_ASSET_BASE)};

      let blobUrl = null;
      let hasExecuted = false;

      /*
       * Flutter's router reports the active route through the History API.
       *
       * This runner is an about:srcdoc document, so it inherits the host page's
       * base URL: the URL Flutter derives resolves to something like
       * https://host/srcdoc, which a document whose own URL is 'about:srcdoc'
       * is not permitted to write. replaceState then throws a SecurityError
       * while WidgetsApp is building, and MaterialApp never mounts.
       *
       * DartPad avoids this only because its runner is a real document at
       * dartpad.dev/frame.html. An embedded example has no business rewriting
       * the address bar regardless, so history is virtualized instead: Flutter
       * reads back exactly what it wrote, and nothing reaches the real session
       * history.
       */
      (function virtualizeHistory() {
        let virtualState = null;

        function writeState(state) {
          virtualState = state === undefined ? null : state;
        }

        try {
          self.history.pushState = writeState;
          self.history.replaceState = writeState;

          Object.defineProperty(self.history, 'state', {
            configurable: true,
            get: function () {
              return virtualState;
            },
          });
        } catch (_) {
          // Leave the native History API in place if it is not patchable.
        }
      })();

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
          return 'Unknown Flutter runtime error';
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
                : stringifyError(message),
          },
          '*'
        );
      }

      // Used by the decorated compiler output, which runs from a Blob.
      self.__flutterLiveSend = send;

      /*
       * DartPad's generated Flutter bootstrap reports framework errors through
       * this global, separately from console output.
       */
      self.reportFlutterError = function (error) {
        send('stderr', error);
      };

      self.addEventListener('unhandledrejection', function (event) {
        send('stderr', event.reason);
      });

      function execute(compiledScript, canvasKitBaseUrl) {
        /*
         * _flutter.loader.loadEntrypoint() guards itself with a one-shot
         * _scriptLoaded flag, so a frame can only ever start one app. The host
         * discards and rebuilds this iframe for every run, exactly as DartPad
         * does.
         */
        if (hasExecuted) {
          return;
        }

        hasExecuted = true;

        try {
          if (
            !self._flutter ||
            !self._flutter.loader ||
            typeof self._flutter.loader.loadEntrypoint !== 'function'
          ) {
            throw new Error('The Flutter web loader failed to initialize.');
          }

          blobUrl = URL.createObjectURL(
            new Blob([compiledScript], { type: 'text/javascript' })
          );

          self._flutter.loader.loadEntrypoint({
            entrypointUrl: blobUrl,
            onEntrypointLoaded: async function (engineInitializer) {
              try {
                send('status', 'Initializing engine');

                const appRunner = await engineInitializer.initializeEngine({
                  canvasKitBaseUrl: canvasKitBaseUrl,
                  assetBase: ASSET_BASE,
                });

                appRunner.runApp();

                send('started');
              } catch (error) {
                send('fatal', error);
              }
            },
          });
        } catch (error) {
          send('fatal', error);
        }
      }

      self.addEventListener('message', function (event) {
        if (event.source !== parent) {
          return;
        }

        const data = event.data;

        if (!data || data.channel !== CHANNEL || data.type !== 'execute') {
          return;
        }

        if (
          typeof data.js !== 'string' ||
          typeof data.canvasKitBaseUrl !== 'string'
        ) {
          send('fatal', 'Invalid Flutter runner payload.');
          return;
        }

        execute(data.js, data.canvasKitBaseUrl);
      });

      self.addEventListener('unload', function () {
        if (blobUrl) {
          URL.revokeObjectURL(blobUrl);
          blobUrl = null;
        }
      });

      self.addEventListener('load', function () {
        send('ready');
      });
    })();
  </script>
</head>

<body></body>
</html>
`;

let cachedVersion: Promise<VersionResponse> | null = null;

/*
 * DartPad's stable channel moves independently of this site, and CanvasKit is
 * addressed by engine SHA, so the version is resolved at runtime rather than
 * pinned. Cached per page load; a stale SHA for the duration of a visit is not
 * a real risk.
 */
function fetchDartPadVersion(): Promise<VersionResponse> {
  if (!cachedVersion) {
    cachedVersion = fetch(VERSION_API, {
      headers: { Accept: 'application/json' },
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error(
            `Unable to read the DartPad runtime version: HTTP ${response.status}.`,
          );
        }

        return response.json() as Promise<VersionResponse>;
      })
      .catch((error) => {
        // Never cache a failure.
        cachedVersion = null;
        throw error;
      });
  }

  return cachedVersion;
}

function splitCode(source: string) {
  const lines = source.split('\n');

  let startIdx = 0;
  let endIdx = lines.length;

  /*
   * Same convention as RustLive/DartLive:
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
    .map((line) => line.replace(/^(\s*)# /, '$1'));

  const footerLines = lines
    .slice(endIdx)
    .map((line) => line.replace(/^(\s*)# /, '$1'));

  return {
    header:
      headerLines.length > 0
        ? `${headerLines.join('\n')}\n`
        : '',

    body: lines.slice(startIdx, endIdx).join('\n'),

    footer:
      footerLines.length > 0
        ? `\n${footerLines.join('\n')}`
        : '',
  };
}

export default function FlutterLive({
  code: initialCode,
  hiddenCode,
  hiddenFile,
}: FlutterLiveProps) {
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

  const [view, setView] =
    useState<View>('code');

  const [output, setOutput] =
    useState<string | null>(null);

  const [isError, setIsError] =
    useState(false);

  const [running, setRunning] =
    useState(false);

  const [status, setStatus] =
    useState('Not running');

  const [hasFrame, setHasFrame] =
    useState(false);

  const [flutterVersion, setFlutterVersion] =
    useState<string | null>(null);

  /*
   * React never renders children into this node, so the iframe can be managed
   * imperatively without fighting reconciliation.
   */
  const previewRef =
    useRef<HTMLDivElement>(null);

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

      setHasFrame(false);
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
    setStatus('Compiling');

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
       * Compile, and resolve the engine SHA that selects the matching
       * CanvasKit build, concurrently.
       */
      const [response, versionData] =
        await Promise.all([
          fetch(COMPILE_API, {
            method: 'POST',

            headers: {
              'Content-Type': 'application/json',
              Accept: 'application/json, text/plain',
            },

            body: JSON.stringify({
              source: fullSource,
            }),

            signal: abortController.signal,
          }),

          fetchDartPadVersion(),
        ]);

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
            `Flutter compiler returned HTTP ${response.status}.`
        );
      }

      let data: CompileResponse;

      try {
        data =
          (await response.json()) as CompileResponse;
      } catch {
        throw new Error(
          'Flutter compiler returned an invalid success response.'
        );
      }

      if (
        typeof data.result !== 'string' ||
        data.result.length === 0
      ) {
        throw new Error(
          'Flutter compiler returned no compiled JavaScript.'
        );
      }

      if (
        typeof versionData.engineVersion !== 'string' ||
        versionData.engineVersion.length === 0
      ) {
        throw new Error(
          'DartPad did not report an engineVersion, so CanvasKit cannot be located.'
        );
      }

      if (
        typeof versionData.flutterVersion === 'string'
      ) {
        setFlutterVersion(
          versionData.flutterVersion
        );
      }

      const canvasKitBaseUrl =
        `https://www.gstatic.com/flutter-canvaskit/${encodeURIComponent(
          versionData.engineVersion
        )}/`;

      const decoratedJs =
        decorateFlutterJavaScript(data.result);

      setStatus('Loading Flutter runtime');

      /*
       * Create an isolated runner.
       *
       * Deliberately DO NOT use allow-same-origin. User Flutter code therefore
       * executes with an opaque origin and cannot reach this site's storage or
       * inspect the parent page. DartPad's own frame.js asserts the same thing
       * (it refuses to run unless window.origin === 'null').
       */
      const iframe =
        document.createElement('iframe');

      iframe.setAttribute(
        'sandbox',
        'allow-scripts'
      );

      iframe.setAttribute(
        'title',
        'Flutter application preview'
      );

      iframe.setAttribute(
        'allow',
        'clipboard-write'
      );

      iframe.className =
        flutterStyles.previewFrame;

      iframe.srcdoc = FLUTTER_RUNNER_HTML;

      iframeRef.current = iframe;

      const capturedLines: string[] = [];

      let startupComplete = false;

      const appendOutput = (
        message: unknown
      ) => {
        const text = String(message ?? '');

        if (!text) {
          return;
        }

        /*
         * Avoid the most common duplicate error case where both the Flutter
         * error reporter and window.onerror report the exact same line.
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

        startupComplete = true;

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
                type: 'execute',
                js: decoratedJs,
                canvasKitBaseUrl,
              },
              '*'
            );

            break;
          }

          case 'status': {
            if (
              typeof data.message === 'string' &&
              !startupComplete
            ) {
              setStatus(data.message);
            }

            break;
          }

          case 'started': {
            setStatus('Running');
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

            /*
             * Flutter reports non-fatal framework errors (overflows, failed
             * assertions in a single build) this way, so a running app keeps
             * running and only the console reflects the problem.
             */
            if (!startupComplete) {
              setStatus('Error');
              stopSpinner();
            }

            break;
          }

          case 'fatal': {
            setIsError(true);

            appendOutput(
              data.message ||
                'Failed to initialize the Flutter runtime.'
            );

            setStatus('Error');
            stopSpinner();
            break;
          }

          default:
            break;
        }
      };

      messageListenerRef.current =
        messageHandler;

      /*
       * The listener is attached before the frame is inserted, so 'ready'
       * cannot be missed.
       */
      window.addEventListener(
        'message',
        messageHandler
      );

      /*
       * The preview stage replaces the editor, so its host node does not exist
       * yet. The effect below attaches the frame once React has rendered it.
       */
      setHasFrame(true);
      setView('preview');

      /*
       * Only protects startup. Once runApp() has succeeded the app is expected
       * to keep running, and arbitrary Flutter code in an iframe cannot be
       * safely interrupted anyway.
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
          setStatus('Timed out');

          appendOutput(
            'Timed out while starting the Flutter runtime.'
          );
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
      setStatus('Error');

      setOutput(
        error instanceof Error
          ? error.message
          : 'Unknown Flutter execution error.'
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

  /*
   * The iframe is built inside runCode() but can only be attached after the
   * preview stage has rendered. Loading starts the moment it lands in the DOM.
   */
  useEffect(() => {
    const iframe = iframeRef.current;
    const host = previewRef.current;

    if (
      view !== 'preview' ||
      !iframe ||
      !host ||
      iframe.parentNode === host
    ) {
      return;
    }

    host.appendChild(iframe);
  }, [view, hasFrame]);

  /*
   * Returning to the editor tears the runner down: the iframe, its Flutter
   * engine and the ~11 MB of SDK it pulled in are all released.
   */
  const backToCode = useCallback(() => {
    activeRunRef.current++;
    cleanupRunner();
    setRunning(false);
    setStatus('Not running');
    setView('code');
  }, [cleanupRunner]);

  const showPreview = view === 'preview';

  return (
    <div
      className={`${styles.container} ${flutterStyles.root}`}
    >
      <div className={styles.toolbar}>
        <div className={styles.toolbarLeft}>
          <span className={styles.langBadge}>
            Flutter
          </span>

          {flutterVersion && (
            <span
              className={flutterStyles.version}
            >
              {flutterVersion}
            </span>
          )}

          {showPreview && (
            <span
              className={flutterStyles.status}
            >
              {running && (
                <span
                  className={
                    flutterStyles.statusSpinner
                  }
                />
              )}
              {status}
            </span>
          )}
        </div>

        {showPreview ? (
          <button
            className={styles.runButton}
            onClick={backToCode}
            title="Stop the app and return to the editor"
          >
            ← Back to code
          </button>
        ) : (
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
                {status}
              </>
            ) : (
              '▶ Run'
            )}
          </button>
        )}
      </div>

      {showPreview ? (
        <div
          className={flutterStyles.previewStage}
        >
          {running && (
            <div
              className={
                flutterStyles.previewOverlay
              }
            >
              <span
                className={
                  flutterStyles.statusSpinner
                }
              />
              {status}…
            </div>
          )}

          <div
            ref={previewRef}
            style={{ height: '100%' }}
          />
        </div>
      ) : (
        <LiveCodeEditor
          language="dart"
          languageLabel="Flutter"
          demo={code}
          onDemoChange={setCode}
          base={includedCode}
          onBaseChange={setIncludedCode}
          hasBase={hasIncludedTab}
          baseFile={hiddenFile}
          indent="  "
          onRun={runCode}
        />
      )}

      {output !== null && (
        <div className={styles.output}>
          <div
            className={styles.outputHeader}
          >
            <span
              className={styles.outputLabel}
            >
              Console
            </span>

            <button
              className={styles.clearButton}
              onClick={() => setOutput(null)}
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
