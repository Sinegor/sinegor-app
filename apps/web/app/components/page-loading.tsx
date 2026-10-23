import { Brand } from "./brand";
import { LabArt } from "./lab-art";
import { Notice } from "./ui";

export function PageLoading({ children }: { children: string }) {
  return (
    <>
      <header className="site-header">
        <Brand compact />
      </header>
      <main id="main" className="container">
        <div className="loading-state">
          <LabArt compact />
          <Notice>{children}</Notice>
        </div>
      </main>
    </>
  );
}
