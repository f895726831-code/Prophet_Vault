# Third-party notices

This project is MIT licensed (see [LICENSE](LICENSE)). It redistributes no third-party
code, but two dependencies deserve a note.

## Apache ECharts (Apache-2.0)

The generated dependency-graph page loads **Apache ECharts 5.5.1** from jsDelivr by
default:

```
https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js
```

Nothing is redistributed by this repository in that mode - the reader's browser fetches
the library, under the licence and privacy terms of the CDN.

If you generate a page with `--echarts <path>`, the library you point at is **copied
verbatim** into the HTML, which makes that page a redistributed Apache-2.0 work. The
minified file keeps its own licence banner, and you are responsible for satisfying
Apache-2.0 when you pass that page on. Upstream:

- <https://github.com/apache/echarts>
- <https://www.apache.org/licenses/LICENSE-2.0>

## Obsidian

Obsidian is a separate application, not bundled here. The generated vault only uses the
plain-Markdown conventions Obsidian understands, so it can also be read in any editor.

## Prophet / Firebird

The toolkit reads a Prophet workspace but ships no vendor code. `isql.exe` is part of the
user's own Prophet/Firebird installation and is invoked as an external process. Prophet is
a trademark of its owner; this project is independent and unofficial.
