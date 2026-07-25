import MDXComponents from '@theme-original/MDXComponents';
import RustLive from '@site/src/components/RustLive';
import DartLive from '@site/src/components/DartLive';
import FlutterLive from '@site/src/components/FlutterLive';

export default {
  ...MDXComponents,
  RustLive, // Registering the component globally
  DartLive, // Registering the component globally
  FlutterLive, // Registering the component globally
};
