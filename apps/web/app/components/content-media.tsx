import type { ReactNode } from "react";
import type { ImageLayout, Media } from "../lib/cms";

/** One presentation contract for covers, section illustrations and previews. */
export function ContentMedia({
  image,
  layout,
  children,
}: {
  image?: Media | null;
  layout?: ImageLayout | null;
  children: ReactNode;
}) {
  if (!image?.url) return <>{children}</>;
  const position = ["top", "left", "right"].includes(layout?.position || "")
    ? layout!.position
    : "top";
  const size = ["small", "medium", "large", "full"].includes(layout?.size || "")
    ? layout!.size
    : "medium";
  const alignment = ["left", "center", "right"].includes(
    layout?.alignment || "",
  )
    ? layout!.alignment
    : "center";
  return (
    <div className="content-media">
      <div
        className={`content-media__layout content-media--${position} content-media--${size} content-media--align-${alignment}`}
      >
        <figure className="content-media__figure">
          <img
            src={image.url}
            alt={image.alternativeText || ""}
            width={image.width && image.width > 0 ? image.width : undefined}
            height={image.height && image.height > 0 ? image.height : undefined}
            className="content-media__image"
          />
          {layout?.caption && <figcaption>{layout.caption}</figcaption>}
        </figure>
        <div className="content-media__body">{children}</div>
      </div>
    </div>
  );
}
