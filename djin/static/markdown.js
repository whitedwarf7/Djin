// Safe Markdown renderer.
// Builds DOM nodes directly and never assigns innerHTML, so model output containing text
// pulled from emails or web pages cannot inject markup or scripts.
(function (global) {
  "use strict";

  const SAFE_PROTOCOLS = ["http:", "https:", "mailto:"];

  const INLINE_PATTERN = [
    "`([^`]+)`", // 1 inline code
    "\\*\\*([\\s\\S]+?)\\*\\*", // 2 bold
    "__([\\s\\S]+?)__", // 3 bold
    "\\*([^*\\n]+?)\\*", // 4 italic
    "(?<![A-Za-z0-9])_([^_\\n]+?)_(?![A-Za-z0-9])", // 5 italic, ignores snake_case
    "~~([\\s\\S]+?)~~", // 6 strikethrough
    "\\[([^\\]]*)\\]\\(((?:[^()\\s]|\\([^()\\s]*\\))+)\\)", // 7 label, 8 href
    "(https?://(?:[^\\s<>()\\[\\]]|\\([^\\s()]*\\))+)", // 9 bare URL
  ].join("|");

  function safeUrl(raw) {
    try {
      const url = new URL(raw, global.location.href);
      return SAFE_PROTOCOLS.includes(url.protocol) ? url.href : null;
    } catch {
      return null;
    }
  }

  function appendText(parent, text) {
    text.split("\n").forEach((piece, index) => {
      if (index > 0) parent.appendChild(document.createElement("br"));
      if (piece) parent.appendChild(document.createTextNode(piece));
    });
  }

  function makeLink(href, label) {
    const url = safeUrl(href);
    if (!url) {
      const span = document.createElement("span");
      appendText(span, label || href);
      return span;
    }
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.target = "_blank";
    anchor.rel = "noopener noreferrer";
    appendText(anchor, label || url);
    return anchor;
  }

  function renderInline(text, parent) {
    const pattern = new RegExp(INLINE_PATTERN, "g"); // fresh instance: this function recurses
    let cursor = 0;
    let match;

    while ((match = pattern.exec(text)) !== null) {
      if (match.index > cursor) appendText(parent, text.slice(cursor, match.index));
      cursor = match.index + match[0].length;

      if (match[1] !== undefined) {
        const code = document.createElement("code");
        code.textContent = match[1];
        parent.appendChild(code);
      } else if (match[2] !== undefined || match[3] !== undefined) {
        parent.appendChild(inlineElement("strong", match[2] ?? match[3]));
      } else if (match[4] !== undefined || match[5] !== undefined) {
        parent.appendChild(inlineElement("em", match[4] ?? match[5]));
      } else if (match[6] !== undefined) {
        parent.appendChild(inlineElement("del", match[6]));
      } else if (match[7] !== undefined) {
        parent.appendChild(makeLink(match[8], match[7]));
      } else if (match[9] !== undefined) {
        parent.appendChild(makeLink(match[9], match[9]));
      }
    }

    if (cursor < text.length) appendText(parent, text.slice(cursor));
    return parent;
  }

  function inlineElement(tagName, text) {
    return renderInline(text, document.createElement(tagName));
  }

  const isHr = (line) => /^\s*([-*_])(\s*\1){2,}\s*$/.test(line);
  const isBullet = (line) => /^\s*[-*+]\s+/.test(line);
  const isOrdered = (line) => /^\s*\d+[.)]\s+/.test(line);
  const isQuote = (line) => /^\s*>/.test(line);

  function isTableSeparator(line) {
    return line.includes("-") && /^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(line);
  }

  function isBlockStart(line) {
    return (
      /^```/.test(line) ||
      /^#{1,6}\s/.test(line) ||
      isQuote(line) ||
      isBullet(line) ||
      isOrdered(line) ||
      isHr(line)
    );
  }

  function splitRow(line) {
    return line
      .trim()
      .replace(/^\|/, "")
      .replace(/\|$/, "")
      .split("|")
      .map((cell) => cell.trim());
  }

  function alignmentOf(spec) {
    const left = spec.startsWith(":");
    const right = spec.endsWith(":");
    if (left && right) return "center";
    if (right) return "right";
    return left ? "left" : "";
  }

  function renderMarkdown(source) {
    const fragment = document.createDocumentFragment();
    const lines = String(source ?? "").replace(/\r\n/g, "\n").split("\n");
    let i = 0;

    while (i < lines.length) {
      const line = lines[i];

      if (!line.trim()) {
        i++;
        continue;
      }

      const fence = line.match(/^```\s*(\S*)/);
      if (fence) {
        const body = [];
        i++;
        while (i < lines.length && !/^```/.test(lines[i])) body.push(lines[i++]);
        i++;
        const pre = document.createElement("pre");
        const code = document.createElement("code");
        if (fence[1]) code.dataset.lang = fence[1];
        code.textContent = body.join("\n");
        pre.appendChild(code);
        fragment.appendChild(pre);
        continue;
      }

      const heading = line.match(/^(#{1,6})\s+(.*)$/);
      if (heading) {
        fragment.appendChild(inlineElement("h" + heading[1].length, heading[2].trim()));
        i++;
        continue;
      }

      if (isHr(line)) {
        fragment.appendChild(document.createElement("hr"));
        i++;
        continue;
      }

      if (line.includes("|") && i + 1 < lines.length && isTableSeparator(lines[i + 1])) {
        const headers = splitRow(line);
        const aligns = splitRow(lines[i + 1]).map(alignmentOf);
        const table = document.createElement("table");
        const headRow = document.createElement("tr");

        headers.forEach((cell, index) => {
          const th = document.createElement("th");
          if (aligns[index]) th.style.textAlign = aligns[index];
          renderInline(cell, th);
          headRow.appendChild(th);
        });

        const thead = document.createElement("thead");
        thead.appendChild(headRow);
        table.appendChild(thead);

        const tbody = document.createElement("tbody");
        i += 2;
        while (i < lines.length && lines[i].trim() && lines[i].includes("|")) {
          const cells = splitRow(lines[i]);
          const row = document.createElement("tr");
          for (let column = 0; column < headers.length; column++) {
            const td = document.createElement("td");
            if (aligns[column]) td.style.textAlign = aligns[column];
            renderInline(cells[column] ?? "", td);
            row.appendChild(td);
          }
          tbody.appendChild(row);
          i++;
        }
        table.appendChild(tbody);
        fragment.appendChild(table);
        continue;
      }

      if (isQuote(line)) {
        const body = [];
        while (i < lines.length && isQuote(lines[i])) {
          body.push(lines[i++].replace(/^\s*>\s?/, ""));
        }
        const quote = document.createElement("blockquote");
        quote.appendChild(renderMarkdown(body.join("\n")));
        fragment.appendChild(quote);
        continue;
      }

      if (isBullet(line) || isOrdered(line)) {
        const ordered = isOrdered(line) && !isBullet(line);
        const matcher = ordered ? /^\s*\d+[.)]\s+(.*)$/ : /^\s*[-*+]\s+(.*)$/;
        const list = document.createElement(ordered ? "ol" : "ul");

        while (i < lines.length) {
          const item = lines[i].match(matcher);
          if (!item) break;
          const parts = [item[1]];
          i++;
          while (
            i < lines.length &&
            lines[i].trim() &&
            /^\s+/.test(lines[i]) &&
            !isBullet(lines[i]) &&
            !isOrdered(lines[i])
          ) {
            parts.push(lines[i].trim());
            i++;
          }
          const li = document.createElement("li");
          renderInline(parts.join(" "), li);
          list.appendChild(li);
        }

        fragment.appendChild(list);
        continue;
      }

      const paragraph = [];
      while (i < lines.length && lines[i].trim() && !isBlockStart(lines[i])) {
        paragraph.push(lines[i++]);
      }
      fragment.appendChild(inlineElement("p", paragraph.join("\n")));
    }

    return fragment;
  }

  global.renderMarkdown = renderMarkdown;
})(window);
