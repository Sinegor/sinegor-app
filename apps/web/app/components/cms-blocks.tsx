import { createElement, Fragment, type ReactNode } from "react";
import type { RichTextNode } from "../lib/cms";

function linkUrl(value: string) {
  try {
    const url = new URL(value, "https://sinegor.invalid");
    return ["http:", "https:", "mailto:", "tel:"].includes(url.protocol)
      ? value
      : undefined;
  } catch {
    return undefined;
  }
}

function listItems(nodes: RichTextNode[]) {
  const items: RichTextNode[] = [];
  for (const node of Array.isArray(nodes) ? nodes : []) {
    if (!node || typeof node !== "object") continue;
    const previous = items.at(-1);
    // Strapi indentation stores a nested list next to its parent list-item.
    if (node.type === "list" && previous?.type === "list-item") {
      items[items.length - 1] = {
        ...previous,
        children: [...previous.children, node],
      };
    } else {
      items.push(
        node.type === "list-item"
          ? node
          : { type: "list-item", children: [node] },
      );
    }
  }
  return items;
}

/** Render Strapi Blocks as semantic HTML during SSR and hydration. */
export function CmsBlocks({ nodes }: { nodes?: RichTextNode[] | null }) {
  if (!Array.isArray(nodes)) return null;
  return nodes.map((node, index) => {
    if (!node || typeof node !== "object") return null;
    let result: ReactNode;
    if (node.type === "text") {
      result = typeof node.text === "string" ? node.text : "";
      if (typeof result === "string" && result.includes("\n")) {
        result = result.split("\n").map((line, lineIndex) => (
          <Fragment key={lineIndex}>
            {lineIndex > 0 && <br />}
            {line}
          </Fragment>
        ));
      }
      if (node.code) result = <code>{result}</code>;
      if (node.bold) result = <strong>{result}</strong>;
      if (node.italic) result = <em>{result}</em>;
      if (node.underline) result = <u>{result}</u>;
      if (node.strikethrough) result = <s>{result}</s>;
    } else {
      const children = <CmsBlocks nodes={node.children} />;
      switch (node.type) {
        case "paragraph":
          result = <p>{children}</p>;
          break;
        case "heading":
          result = createElement(
            [1, 2, 3, 4, 5, 6].includes(node.level) ? `h${node.level}` : "h2",
            null,
            children,
          );
          break;
        case "list":
          result =
            node.format === "ordered" ? (
              <ol>
                <CmsBlocks nodes={listItems(node.children)} />
              </ol>
            ) : (
              <ul>
                <CmsBlocks nodes={listItems(node.children)} />
              </ul>
            );
          break;
        case "list-item":
          result = <li>{children}</li>;
          break;
        case "quote":
          result = <blockquote>{children}</blockquote>;
          break;
        case "code":
          result = (
            <pre>
              <code>{children}</code>
            </pre>
          );
          break;
        case "link": {
          const href =
            typeof node.url === "string" ? linkUrl(node.url) : undefined;
          result = href ? <a href={href}>{children}</a> : children;
          break;
        }
        case "image": {
          const src = node.image?.url;
          result =
            src && /^https?:\/\//i.test(src) ? (
              <img
                src={src}
                alt={node.image.alternativeText || ""}
                width={node.image.width || undefined}
                height={node.image.height || undefined}
              />
            ) : null;
          break;
        }
        default:
          result = children;
      }
    }
    return <Fragment key={index}>{result}</Fragment>;
  });
}
