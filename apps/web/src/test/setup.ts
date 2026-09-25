import "@testing-library/jest-dom/vitest";

// O jsdom não rola a página; o app pede rolagem ao trocar de tela.
window.scrollTo = (() => undefined) as typeof window.scrollTo;

// Nem toca mídia: a paisagem do login pede `play()` ao vídeo decorativo.
HTMLMediaElement.prototype.play = () => Promise.resolve();
