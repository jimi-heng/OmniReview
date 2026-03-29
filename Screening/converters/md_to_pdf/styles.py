CSS = """\
@page {
    size: A4;
    margin: 20mm 18mm;
}

body {
    font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
    font-size: 11pt;
    line-height: 1.6;
    color: #222;
}

/* Headings
   Defines font size, spacing, and hierarchy for headings (h1–h6).
*/
h1 { font-size: 20pt; margin-top: 0.8em; margin-bottom: 0.4em; }
h2 { font-size: 16pt; margin-top: 0.7em; margin-bottom: 0.35em; border-bottom: 1px solid #ccc; padding-bottom: 0.15em; }
h3 { font-size: 13pt; margin-top: 0.6em; margin-bottom: 0.3em; }
h4 { font-size: 11.5pt; margin-top: 0.5em; margin-bottom: 0.25em; }
h5, h6 { font-size: 11pt; margin-top: 0.4em; margin-bottom: 0.2em; }

/* Paragraphs & Lists
   Controls spacing and indentation for paragraphs and list elements.
*/
p { margin: 0.4em 0; }
ul, ol { margin: 0.3em 0; padding-left: 1.8em; }
li { margin-bottom: 0.15em; }

/* Tables
   Defines layout, borders, alternating row colors, and hover effects.
*/
table {
    width: 100%;
    border-collapse: collapse;
    margin: 0.8em 0;
    font-size: 9.5pt;
    page-break-inside: auto;
}
thead th {
    background-color: #34495e;
    color: #fff;
    font-weight: bold;
    text-align: left;
    padding: 6px 8px;
    border: 1px solid #2c3e50;
}
tbody td {
    padding: 5px 8px;
    border: 1px solid #ddd;
    vertical-align: top;
}
tbody tr:nth-child(even) {
    background-color: #f7f8fa;
}
tbody tr:hover {
    background-color: #eef1f5;
}

/* Code Blocks
   Styles multi-line code blocks with background, padding, and wrapping.
*/
pre {
    background-color: #f4f4f4;
    border: 1px solid #ddd;
    border-radius: 4px;
    padding: 10px 12px;
    font-size: 9pt;
    line-height: 1.45;
    overflow-x: auto;
    white-space: pre-wrap;
    word-wrap: break-word;
    margin: 0.6em 0;
}
pre code {
    background: none;
    border: none;
    padding: 0;
    border-radius: 0;
    font-size: inherit;
}

/* Inline Code
   Styles inline code elements within text.
*/
code {
    background-color: #eef0f3;
    border: 1px solid #ddd;
    border-radius: 3px;
    padding: 1px 4px;
    font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, Courier, monospace;
    font-size: 0.9em;
}

/* Horizontal Rules
   Defines separator line style between sections.
*/
hr {
    border: none;
    border-top: 1px solid #ccc;
    margin: 1em 0;
}

/* Block Quotes
   Styles quoted text with left border and background.
*/
blockquote {
    border-left: 4px solid #ccc;
    margin: 0.6em 0;
    padding: 0.3em 1em;
    color: #555;
    background: #fafafa;
}

/* Images
   Ensures responsive image scaling within layout.
*/
img {
    max-width: 100%;
    height: auto;
}
"""

MD_EXTENSIONS = [
    "tables",
    "fenced_code",
    "codehilite",
    "toc",
    "nl2br",
    "sane_lists",
]

MD_EXTENSION_CONFIGS = {
    "codehilite": {
        "css_class": "highlight",
        "guess_lang": False,
        "noclasses": True,
    },
}