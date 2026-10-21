"""Local viewport measurements for the responsive transaction editor."""

import streamlit as st


def editor_viewport() -> tuple[int, int]:
    component = st.components.v2.component(
        "editor_viewport",
        html=(
            '<div class="editor-viewport-sensor" aria-hidden="true" '
            'style="height:1px;width:100%"></div>'
        ),
        isolate_styles=False,
        js="""export default function({parentElement, setStateValue}) {
          const root = parentElement.querySelector('.editor-viewport-sensor');
          const measure = () => {
            const width = root.getBoundingClientRect().width;
            const value = {narrow: width < 520, height: Math.round(window.innerHeight * .55)};
            const signature = JSON.stringify(value);
            if (width > 0 && signature !== root.dataset.size) {
              root.dataset.size = signature; setStateValue('size', value);
            }
          };
          const observer = new ResizeObserver(measure);
          observer.observe(root);
          window.addEventListener('resize', measure);
          measure();
          return () => {observer.disconnect(); window.removeEventListener('resize', measure);};
        }""",
    )
    result = component(
        key="editor_viewport",
        default={"size": {"narrow": False, "height": 520}},
        on_size_change=lambda: None,
    )
    size = result.size or {"narrow": False, "height": 520}
    return (1 if size["narrow"] else 0, max(180, min(520, int(size["height"]))))
