import wideArt from "../../assets/AI Core and Holographic Justice.png";
import compactArt from "../../assets/Sinegor AI Device with Holographic Scales.png";

export function LabArt({
  compact = false,
  className = "",
  desktopOnly = false,
}: {
  compact?: boolean;
  className?: string;
  desktopOnly?: boolean;
}) {
  const image = (
    <img
      className={`lab-art ${className}`}
      src={compact ? compactArt : wideArt}
      alt=""
      aria-hidden="true"
      width={compact ? 1298 : 1774}
      height={compact ? 1212 : 887}
      decoding="async"
    />
  );
  if (!desktopOnly) return image;
  return (
    <picture style={{ display: "contents" }}>
      {/* Native source selection also prevents React's unconditional image preload. */}
      <source
        style={{ display: "none" }}
        media="(max-width: 767px)"
        srcSet="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
      />
      {image}
    </picture>
  );
}
