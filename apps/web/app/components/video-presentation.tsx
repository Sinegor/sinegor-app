import { useEffect, useRef, useState } from "react";
import presentationPoster from "../../assets/заставка.jpg";
import { Notice } from "./ui";
import { useAnalytics } from "./public-analytics";

// Remount the media state when an editor replaces the CMS video.
export function VideoPresentation({
  src,
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
      key={src?.trim() || undefined}
      src={src?.trim() || undefined}
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
  src?: string;
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
      src &&
      (video?.error ||
        video?.networkState === HTMLMediaElement.NETWORK_NO_SOURCE)
    )
      setFailed(true);
  }, [src]);
  return (
    <figure className="hero-video">
      <div className="video-heading">
        <span>Видеопрезентация</span>
        <span className="video-brand">SINEGOR LAB</span>
      </div>
      <video
        ref={videoRef}
        controls={!!src}
        playsInline
        preload="metadata"
        poster={poster}
        aria-label="Видеопрезентация SINEGOR LAB"
        onPlaying={() => analytics("video_presentation_view")}
        onError={() => setFailed(true)}
      >
        {src && (
          <>
            <source src={src} type={type} onError={() => setFailed(true)} />
            Ваш браузер не поддерживает видео. <a href={src}>Скачать ролик</a>
          </>
        )}
      </video>
      <figcaption>{caption}</figcaption>
      {!src && <Notice>Видеопрезентация пока недоступна.</Notice>}
      {src && failed && (
        <Notice error>
          Не удалось загрузить видео. <a href={src}>Открыть видео отдельно</a>
          {" или обновите страницу, чтобы повторить загрузку."}
        </Notice>
      )}
    </figure>
  );
}
