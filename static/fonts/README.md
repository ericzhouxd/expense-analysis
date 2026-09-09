# Local font assets

These public assets contain no spending data. Fonts are served by the local app;
there are no runtime Google Fonts requests.

- Anton Regular: condensed display numerals, from Google Fonts / Vernon Adams.
- Departure Mono Regular 1.500: interface, labels, tables and charts, by Helena Zhang.
- Jizhang-Wordmark.ttf: Google Fonts Noto Sans TC 900 subset containing only
  `記帳` (U+8A18, U+5E33), used only for the wordmark.

Each font's SIL Open Font License is included alongside it. Departure Mono was
obtained from its official GitHub repository on 2026-09-09; the other fonts came
from fonts.gstatic.com, with licenses from github.com/google/fonts on 2026-09-08.
The three font families are the entire designed type system (weights are not
additional families). Operating-system fallbacks may render other scripts in
user-entered descriptions.

Keep this directory public-assets-only. Never copy databases, exports, or user
configuration here: Streamlit's static-file server can serve its contents.
