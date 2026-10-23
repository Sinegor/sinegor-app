import wideArt from "../../assets/AI Core and Holographic Justice.png";
import compactArt from "../../assets/Sinegor AI Device with Holographic Scales.png";

export function LabArt({
  compact = false,
  className = "",
}: {
  compact?: boolean;
  className?: string;
}) {
  return (
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
}
