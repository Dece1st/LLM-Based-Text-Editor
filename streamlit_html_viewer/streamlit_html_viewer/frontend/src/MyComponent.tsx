import React, { useEffect, useState } from "react"
import {
  Streamlit,
  withStreamlitConnection,
  ComponentProps,
} from "streamlit-component-lib"

function MyComponent(props: ComponentProps) {
  const initialHtml = props.args.html as string
  const height      = (props.args.height as number) || 400

  const [content, setContent] = useState(initialHtml)

  // Sync when Python re‑renders
  useEffect(() => setContent(initialHtml), [initialHtml])

  function onClick(e: React.MouseEvent) {
    const tgt = e.target as HTMLElement
    if (tgt.classList.contains("toggle")) {
      const orig = tgt.dataset.original!
      const corr = tgt.dataset.corrected!
      const now  = tgt.textContent === orig ? corr : orig
      tgt.textContent = now
      tgt.style.background = now === corr ? "#2EBD2E" : "#DB0000"

      // send updated HTML back to Python immediately
      const updated = document.getElementById("content")!.innerHTML
      Streamlit.setComponentValue(updated)
    }
  }

  return (
    <div onClick={onClick}>
      <div
        id="content"
        style={{ height: `${height}px`, overflowY: "auto" }}
        dangerouslySetInnerHTML={{ __html: content }}
      />
    </div>
  )
}

export default withStreamlitConnection(MyComponent)