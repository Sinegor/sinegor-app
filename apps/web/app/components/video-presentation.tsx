import { useEffect, useRef, useState } from "react";
import presentation from "../../assets/Презентация_1.1.mp4";
import presentationPoster from "../../assets/заставка.jpg";
import { Notice } from "./ui";
import { useAnalytics } from "./public-analytics";

// Remount the media state when an editor replaces the CMS video.
export function VideoPresentation({
  src = presentation,
  type = "video/mp4",
  poster = presentationPoster,
  caption = "Видеопрезентация SINEGOR LAB.",
}: {
  src?: string;
  type?: string;
  poster?: string;
  caption?: string;
}) {
  return (
    <PresentationMedia
      key={src}
      src={src}
      type={type}
      poster={poster}
      caption={caption}
    />
  );
}

function PresentationMedia({
  src,
  type,
  poster,
  caption,
}: {
  src: string;
  type: string;
  poster: string;
  caption: string;
}) {
  const [failed, setFailed] = useState(false);
  const analytics = useAnalytics();
  const videoRef = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    // SSR media requests can fail before React attaches the error handlers.
    const video = videoRef.current;
    if (
      video?.error ||
      video?.networkState === HTMLMediaElement.NETWORK_NO_SOURCE
    )
      setFailed(true);
  }, []);
  return (
    <figure className="hero-video">
      <div className="video-heading">
        <span>Видеопрезентация</span>
        <span className="video-brand">SINEGOR LAB</span>
      </div>
      <video
        ref={videoRef}
        controls
        playsInline
        preload="metadata"
        poster={poster}
        aria-label="Видеопрезентация SINEGOR LAB"
        onPlaying={() => analytics("video_presentation_view")}
        onError={() => setFailed(true)}
      >
        <source src={src} type={type} onError={() => setFailed(true)} />
        Ваш браузер не поддерживает видео. <a href={src}>Скачать ролик</a>
      </video>
      <figcaption>{caption}</figcaption>
      {failed && (
        <Notice error>
          Не удалось загрузить видео. <a href={src}>Открыть видео отдельно</a>
          {" или обновите страницу, чтобы повторить загрузку."}
        </Notice>
      )}
    </figure>
  );
}
