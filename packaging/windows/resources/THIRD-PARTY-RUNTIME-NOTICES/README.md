# Runtime redistribution notices

These notices accompany the Windows Python runtime and its linked libraries.
The texts are retained from the immutable python-build-standalone source commit
`4bb01f09aaf362c71e891be4a41cb6d6ddf830b3` (release `20260901`). `sources.json`
records each original URL and SHA-256. The bundled runtime's own
`runtime/LICENSE.txt` and Tcl/Tk notices remain in place. Third-party Python
packages retain their license files and distribution metadata under
`runtime/Lib/site-packages`.

Python is distributed by the Python Software Foundation and its contributors;
this application is independently maintained. The runtime binaries are not
modified. Application packaging removes pip, headers, import libraries, cached
bytecode and selected developer/test directories, adds relative isolated import
paths, and installs the locked application dependencies alongside the runtime.

The NMR Companion MIT license does not replace third-party license terms.
