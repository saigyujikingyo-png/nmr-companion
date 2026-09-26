# Native desktop runtime notices and corresponding sources

NMR Companion uses Qt Widgets through PySide6 Essentials and shiboken6 6.11.2,
with pyqtgraph 0.14.0. Qt and Qt for Python are copyright The Qt Company Ltd.
and their respective contributors. The application MIT license does not replace
any dependency license. No commercial Qt license is claimed by this package.

The Qt for Python package metadata declares the open-source license alternatives
LGPL-3.0-only, GPL-2.0-only and GPL-3.0-only. The following exact upstream texts
are included alongside the unmodified wheel metadata and license files:

- [GNU LGPL version 3](licenses/da7eabb7bafdf7d3ae5e9f223aa5bdc1eece45ac569dc21b3b037520b4464768.txt)
- [GNU GPL version 3, incorporated by LGPL version 3](licenses/8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903.txt)
- [pyqtgraph MIT license and copyright](licenses/b4ed24d468da61df9028a52abe9283a592e63f315943a1c86cd96a9ea5b62079.txt)

`sources.json` maps every copied license and attribution record to its original
upstream path, immutable Git commit, public source archive and SHA-256. Each
`attributions/*.json` record retains the upstream component name, copyright,
license and source information. `licenses/` contains the associated full texts;
identical texts are stored once under their content hash. The collection covers
the upstream Qt modules included in the Essentials wheel, including notices for
some platform or optional components that the Windows workbench does not use.
`qt-library-sources.json` maps each reviewed Qt DLL name to one of those modules.
The builder inventories every shipped `Qt6*.dll`, including nested directories,
and rejects an unlisted library or a module without pinned source notices. The
resulting per-library inventory is included in `build-evidence.json`.

The source repositories and complete corresponding source archives are publicly
available at the exact revisions recorded in `sources.json`:

- Qt 6.11.2: qtbase, qtdeclarative, qttools, qtsvg, qtlottie and qtquicktimeline.
- PySide6 and shiboken6 6.11.2: pyside-setup, including its build instructions.
- pyqtgraph 0.14.0: pyqtgraph.

License choices differ by module. In particular, the pinned upstream build
definitions for [qtlottie](https://github.com/qt/qtlottie/blob/2b64c8abf2476eb2278283b54412131c5d444f19/src/CMakeLists.txt)
and [qtquicktimeline](https://github.com/qt/qtquicktimeline/blob/31aaa7427b4e653f5dd9ceaad1773b1bbd750d74/src/CMakeLists.txt)
declare their libraries as commercial-or-GPL-3.0. Their GPL license texts and
corresponding source links are included; the package does not describe these
optional retained modules as LGPL libraries.

The optional `opengl32sw.dll` is retained from the Qt wheel. Embedded version
strings identify Mesa 11.2.2 and LLVM 3.6.2. Their original notices and public
source archives are recorded separately in `auxiliary-sources.json`. This is
upstream component identification, not a claim that this project rebuilt the
vendor's DLL. Microsoft C/C++ runtime DLLs remain unmodified vendor components.

The package retains dynamically loaded Qt DLLs, Python bindings, the Windows
`qwindows.dll` platform plugin and the isolated test `qoffscreen.dll` plugin.
The unused Qt Designer browser plugin and browser-only type stubs are omitted;
Qt WebEngine, Qt WebView and PySide Addons are not part of the delivered runtime.
No Qt library is statically linked into the application launcher.

Users may replace the shared Qt libraries and bindings with ABI-compatible
modified versions. The launcher does not enforce hashes on these libraries.
The application's terms do not restrict reverse engineering for debugging such
modifications. Installation verification reports changed files, and installation
management preserves them instead of overwriting them; use a separate runtime
copy for a maintained custom library build. Keep these notices with redistributed
copies and consult the applicable license texts for their full terms.

Maintainers reproduce the main notice collection with
`packaging/windows/collect_native_notices.py`. Ordinary release builds only
verify the committed local notices; they do not retrieve license texts online.
The Windows launcher source is publicly included in the NMR Companion source
repository at `packaging/windows/NativeLauncher.cs`, under the application MIT
license. It is compiled with the Windows-provided .NET Framework compiler.
